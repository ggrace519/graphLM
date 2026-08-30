"""Project scanner — walk directory tree, read file contents, skip noise."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns that are always excluded (in addition to user-specified ones)
_ALWAYS_EXCLUDE = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",  # Hypothesis example DB — thousands of cache files
    ".tox",
    ".eggs",
    "*.egg-info",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    ".gitignore",
    ".gitkeep",
    # Build / dist / cache output. These match on any path component, so a
    # legitimately-named source dir called "build"/"dist"/"target" anywhere in
    # the tree is also excluded — an accepted trade-off (precedent: bare "env"
    # above already excludes any component named env). They only remove files
    # from analysis; no security invariant depends on them. Together with the
    # per-directory tree cap, this keeps huge polyglot repos (Rust target/,
    # JS build/, hypothesis caches) from overflowing the LLM context (#17).
    "target",  # Rust/Java build output (crates/*/target/... is thousands of files)
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".terraform",
    ".gradle",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
}

# Hard cap on how many listed children any one directory contributes to the
# pass-1 tree. Bounds tree size independently of the exclude list so a huge or
# junk-heavy directory (e.g. thousands of generated files the excludes missed)
# cannot blow the LLM context window (#17). See scan_project for the rationale
# on capping per-directory rather than globally.
_MAX_TREE_ENTRIES_PER_DIR = 200
# The total tree-line ceiling is this multiple of the per-directory cap. The
# per-directory cap alone bounds the tree at per_dir × (number of directories);
# this multiplier turns that into an absolute ceiling (default 200 × 25 = 5000
# lines ≈ well under the context budget) that holds no matter how many
# directories a repo has.
_TREE_TOTAL_LINE_MULTIPLIER = 25

# Binary extensions that should never be read as text
_BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".svg",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".whl",
    ".so",
    ".dll",
    ".dylib",
    ".o",
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}

# Secret-bearing file extensions — never read these
_SECRET_EXTS = {
    # TLS / certificate / key files
    ".pem",
    ".key",
    ".crt",
    ".cert",
    ".p12",
    ".pfx",
    ".jks",
    ".cer",
    # SSH keys
    ".ppk",
    # Database credentials / connection strings
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.dev",
    ".env.secret",
    ".env.override",
    "env.local",
    "env.production",
    "env.staging",
    "env.secret",
}

# Glob patterns for secret-bearing file stems/names.
# Checked against both the stem and the full filename.
_SECRET_NAME_PATTERNS = {
    "*secrets*",
    "*credentials*",
    "*private*",
    "*password*",
    "*token*",
    "*api*key*",
    "*auth*key*",
}

# Any dotenv-style file (.env, .env.<anything>) is treated as secret-bearing,
# EXCEPT these deliberately-committed, non-secret template variants which are
# scanned normally (they document required vars without holding real values).
_ENV_SAFE_SUFFIXES = ("example", "sample", "template", "dist")

# Source-code extensions that should NOT be excluded by name patterns
# to avoid false positives (e.g. token.py, credentials.py).
_SOURCE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".h", ".hpp"}


class FileFragment:
    """A single file's path and content for inclusion in LLM context."""

    __slots__ = ("rel_path", "content", "estimated_tokens")

    def __init__(self, rel_path: str, content: str, estimated_tokens: int) -> None:
        self.rel_path = rel_path
        self.content = content
        self.estimated_tokens = estimated_tokens


class ScanResult:
    """Result of scanning a project directory."""

    __slots__ = ("tree", "file_fragments", "skipped_count", "excluded_patterns")

    def __init__(
        self,
        tree: str,
        file_fragments: list[FileFragment],
        skipped_count: int,
        excluded_patterns: tuple[str, ...],
    ) -> None:
        self.tree = tree
        self.file_fragments = file_fragments
        self.skipped_count = skipped_count
        self.excluded_patterns = excluded_patterns


def estimate_tokens(text: str) -> int:
    """Fast heuristic token count, calibrated conservatively.

    Real measurement against the served model on graphlm's own content (dense
    directory trees + source code) put the ratio at ~2.83–2.87 bytes/token, so
    the old ~4-bytes/token assumption *under*-counted by ~28% — enough to pack a
    prompt the model then rejected or timed out on (issue #17). We deliberately
    assume 2.5 bytes/token (``* 2 // 5``) so the estimate sits ~13% *above* the
    real count: over-estimating trims a few extra files but keeps the budget a
    real guarantee, whereas under-estimating overflows the context. This is the
    single source of truth for the heuristic — ``context.py`` imports it.
    """
    return len(text.encode("utf-8")) * 2 // 5


def _should_exclude(rel_path: str, exclude_patterns: tuple[str, ...]) -> bool:
    """Check if a relative path matches any exclusion pattern."""
    parts = Path(rel_path).parts
    for pattern in exclude_patterns:
        # Match against the full relative path
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # Match against individual path components
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _is_binary(path: Path) -> bool:
    """Check if a file is likely binary by extension."""
    return path.suffix.lower() in _BINARY_EXTS


def _is_sensitive_file(path: Path) -> bool:
    """Check if a file likely contains secrets or credentials.

    Checks file extension against known secret-bearing extensions and
    filename glob patterns for common secret-credential naming conventions.
    """
    suffix = path.suffix.lower()
    if suffix in _SECRET_EXTS:
        return True

    # Check full filename for non-dot-prefixed patterns like "env.production"
    if path.name.lower() in _SECRET_EXTS:
        return True

    # Any dotenv file (.env, .env.<anything>) is secret-bearing, except the
    # non-secret template variants. A fixed allowlist (_SECRET_EXTS) missed
    # arbitrary variants like .env.qa / .env.test; this catches them all.
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        env_suffix = name[len(".env.") :] if name.startswith(".env.") else ""
        if env_suffix not in _ENV_SAFE_SUFFIXES:
            return True

    stem = path.stem.lower()
    # Only apply name-based patterns to non-source files
    if suffix not in _SOURCE_EXTS:
        for pattern in _SECRET_NAME_PATTERNS:
            if fnmatch.fnmatch(stem, pattern) or fnmatch.fnmatch(path.name.lower(), pattern):
                return True
    return False


def _redact_secrets(content: str) -> str:
    """Replace secret-like patterns in file content with redaction markers.

    This is a best-effort redaction — it catches common patterns but is not
    a substitute for proper secret management.
    """
    redacted = content

    # AWS access key IDs (AKIA...)
    redacted = re.sub(
        r'(AKIA[0-9A-Z]{16})',
        r'[REDACTED:AWS_ACCESS_KEY]',
        redacted,
    )

    # AWS secret access keys (40-char base64-like string, usually preceded by
    # "aws_secret_access_key" or similar context; the generic pattern catches
    # standalone values too)
    redacted = re.sub(
        r'(?i)(aws_secret[_\s]*(?:access_)?key)\s*[=\s:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?',
        r'\1=[REDACTED:AWS_SECRET_KEY]',
        redacted,
    )

    # GitHub / GITHUB_TOKEN patterns
    redacted = re.sub(
        r'(?i)(gh[pousr]_[A-Za-z0-9_]{36,})',
        r'[REDACTED:GITHUB_TOKEN]',
        redacted,
    )

    # Generic bearer / API key assignments
    redacted = re.sub(
        r'(?i)((?:api[_-]?key|apikey)\s*[=:]\s*)["\']?([A-Za-z0-9_\-/+=]{20,})["\']?',
        r'\1"[REDACTED:API_KEY]"',
        redacted,
    )

    # Private key headers
    redacted = re.sub(
        r'(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)',
        r'[REDACTED:PRIVATE_KEY_HEADER]',
        redacted,
    )
    redacted = re.sub(
        r'(-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)',
        r'[REDACTED:PRIVATE_KEY_HEADER]',
        redacted,
    )

    # Password assignments (KEY = value patterns)
    redacted = re.sub(
        r"(?i)((?:password|passwd|pwd)\s*[=:]\s*)([\"']?)(?!none|null|false|true|''|\"\"|\$\{)"
        r"[^\s\"',}]+\2",
        r"\1\2[REDACTED:PASSWORD]\2",
        redacted,
    )

    # Connection strings with embedded passwords
    redacted = re.sub(
        r'((?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^:\s]+:)([^@\s]+)(@)',
        r'\1[REDACTED:CONN_STRING_PASSWORD]\3',
        redacted,
    )

    # Long random-looking strings assigned to variable names suggesting secrets
    redacted = re.sub(
        r'((?:secret|token|key|password|credential|auth)[^\s=]*\s*=\s*)["\']?([A-Za-z0-9_\-/+=]{32,})["\']?',
        r'\1"[REDACTED:SECRET]"',
        redacted,
        flags=re.IGNORECASE,
    )

    return redacted


def _path_is_inside(project_dir: Path, target: Path) -> bool:
    """Check if target path is inside (or equal to) project_dir.

    Handles symlinks by resolving the parent of each path component,
    which prevents symlink traversal attacks.
    """
    try:
        # Resolve both paths
        project_resolved = project_dir.resolve()
        target_resolved = target.resolve()
        # Check containment via commonpath
        common = str(project_resolved)
        return str(target_resolved).startswith(common + "/") or str(target_resolved) == common
    except (ValueError, OSError):
        return False


def scan_project(
    project_dir: Path,
    *,
    max_file_chars: int = 4000,
    max_files: int = 200,
    include_tests: bool = True,
    exclude_patterns: tuple[str, ...] = (),
    redact_secrets: bool = True,
    max_tree_entries_per_dir: int = _MAX_TREE_ENTRIES_PER_DIR,
) -> ScanResult:
    """Walk project directory, build annotated tree, read file contents.

    Args:
        project_dir: Root directory to scan.
        max_file_chars: Maximum characters to read per file.
        max_files: Maximum number of source files to include in context.
        include_tests: Whether to include test files.
        exclude_patterns: Additional glob patterns to exclude.
        redact_secrets: If True, redact secret-like patterns from file content.
        max_tree_entries_per_dir: Cap on how many *listed* children (after
            excludes) any single directory contributes to the pass-1 tree.
            Beyond it, a "… N more entries not shown" marker is emitted and the
            rest of that directory's children are omitted from the tree. This
            is a hard bound on tree size that does not depend on the exclude
            list catching every junk dir — the tree (the whole pass-1 prompt)
            would otherwise grow unbounded with repo size and overflow the LLM
            context on large/polyglot repos (#17). Capping per-directory rather
            than globally keeps the budget spread across the tree so deeply
            nested source dirs stay visible instead of being crowded out by an
            early alphabetical cache directory. It bounds only the tree text,
            not which files are read (that is ``max_files``).

    Returns:
        ScanResult with tree string and file fragments.
    """
    project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # Combine always-excluded with user patterns
    all_exclude = tuple(_ALWAYS_EXCLUDE | set(exclude_patterns))

    # Phase 1: Build the directory tree
    tree_lines = [str(project_dir.name) + "/"]
    skipped_count = 0
    # Absolute ceiling on total tree lines — the per-directory cap alone only
    # bounds the tree at max_tree_entries_per_dir × (number of directories), so
    # a repo with thousands of directories could still overflow. This total
    # backstop makes "the pass-1 tree is bounded" a real guarantee regardless of
    # directory count (#17). Once hit, the walk stops and a final marker is
    # appended after the loop.
    max_tree_lines = max_tree_entries_per_dir * _TREE_TOTAL_LINE_MULTIPLIER
    tree_stopped = False

    def _walk_dir(dir_path: Path, indent: str = "  ") -> None:
        nonlocal skipped_count, tree_stopped
        if tree_stopped:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            skipped_count += 1
            return

        # Phase A — keep only the entries that are actually listable in the
        # tree (everything the skip filters below would have dropped is counted
        # into skipped_count now, so the per-directory cap below counts real
        # listed entries, not raw children, and the "N more" figure is exact).
        listable: list[Path] = []
        for entry in entries:
            rel_str = str(entry.relative_to(project_dir))

            if _should_exclude(rel_str, all_exclude):
                skipped_count += 1
                continue

            # Skip any symlink (file or directory) that points outside the
            # project — otherwise an external symlinked file is listed in the
            # tree and consumes a max_files slot, even though its content is
            # blocked later by the _path_is_inside check before reading.
            if entry.is_symlink() and not _path_is_inside(project_dir, entry):
                skipped_count += 1
                continue

            if not entry.is_dir():
                if _is_binary(entry):
                    skipped_count += 1
                    continue
                if _is_sensitive_file(entry):
                    skipped_count += 1
                    continue
                if not include_tests and (
                    rel_str.startswith("test") or rel_str.startswith("tests/")
                ):
                    # Check test prefix more carefully
                    if "test" in rel_str.split("/")[-1].lower().split(".")[0]:
                        skipped_count += 1
                        continue
                    # Also catch tests/ prefix
                    parts = rel_str.split("/")
                    if parts[0] == "tests" or parts[0].startswith("test_"):
                        skipped_count += 1
                        continue

            listable.append(entry)

        # Phase B — emit up to max_tree_entries_per_dir listed entries, then a
        # single "… N more entries not shown" marker. This is the hard tree-size
        # bound: it is independent of whether the exclude list caught this dir.
        shown = listable[:max_tree_entries_per_dir]
        omitted = len(listable) - len(shown)
        for entry in shown:
            # Total-lines backstop: stop the whole walk once the tree reaches
            # its absolute ceiling, regardless of directory count.
            if len(tree_lines) >= max_tree_lines:
                tree_stopped = True
                return
            rel_str = str(entry.relative_to(project_dir))
            if entry.is_dir():
                tree_lines.append(f"{indent}{rel_str}/")
                _walk_dir(entry, indent + "  ")
            else:
                tree_lines.append(f"{indent}{rel_str}")
        if omitted:
            tree_lines.append(
                f"{indent}… {omitted} more entries not shown "
                f"(tree capped at {max_tree_entries_per_dir} per directory)"
            )
            skipped_count += omitted

    _walk_dir(project_dir)
    if tree_stopped:
        tree_lines.append(
            f"… tree truncated at {max_tree_lines} total lines "
            "(too many directories to list in full)"
        )
    tree = "\n".join(tree_lines)

    # Phase 2: Select and read files for context
    # Priority ranking: config files first, then package init, then source, then tests
    file_fragments: list[FileFragment] = []
    file_count = 0

    def _rank_file(rel_path: str) -> int:
        """Lower number = higher priority."""
        name = rel_path.lower()
        # Top-level config files get highest priority
        config_files = {
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "Gemfile",
            "Makefile",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "README.md",
            "setup.py",
            "setup.cfg",
            "tsconfig.json",
            "next.config.js",
            "vite.config.js",
            "webpack.config.js",
            "tailwind.config.js",
            "postcss.config.js",
            "eslintrc.js",
            "prettier.config.js",
            "rust-toolchain",
            ".dockerignore",
            ".gitignore",
        }
        if name in config_files:
            return 0
        if name.endswith("/__init__.py") or name.endswith("/__init__.js"):
            return 1
        if name.endswith("/main.py") or name.endswith("/main.js"):
            return 2
        if "test" in name.split("/")[-1].lower().split(".")[0]:
            return 10
        return 5

    # Collect all text files, ranked
    all_files: list[tuple[int, Path]] = []
    for root, dirs, files in os.walk(project_dir):
        # Check if we're still inside the project (handles symlinks)
        current_root = Path(root)
        if not _path_is_inside(project_dir, current_root):
            dirs.clear()
            continue

        dirs[:] = [
            d for d in dirs
            if not _should_exclude(str(Path(root, d).relative_to(project_dir)), all_exclude)
            # Also exclude symlinks pointing outside project
            and (not Path(root, d).is_symlink() or _path_is_inside(project_dir, Path(root, d)))
        ]
        for fname in files:
            fpath = Path(root, fname)
            rel = str(fpath.relative_to(project_dir))

            if _should_exclude(rel, all_exclude):
                continue
            # Drop symlinked files that point outside the project BEFORE ranking,
            # so an escaping symlink never occupies a max_files candidate slot
            # (it was previously only rejected at read time, after the slice).
            if fpath.is_symlink() and not _path_is_inside(project_dir, fpath):
                skipped_count += 1
                continue
            if _is_binary(fpath):
                continue
            if _is_sensitive_file(fpath):
                skipped_count += 1
                continue
            if not include_tests:
                parts = rel.split("/")
                if "test" in parts[-1].lower().split(".")[0]:
                    continue
                if parts[0] in ("tests",) or parts[0].startswith("test_"):
                    continue

            try:
                rank = _rank_file(rel)
                all_files.append((rank, fpath))
            except (OSError, PermissionError):
                skipped_count += 1

    # Sort by rank, then by path for determinism
    all_files.sort(key=lambda x: (x[0], str(x[1])))

    # Read up to max_files
    for _rank, fpath in all_files[:max_files]:
        # Double-check the resolved path is inside project
        if not _path_is_inside(project_dir, fpath):
            skipped_count += 1
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            truncated = False
            if len(content) > max_file_chars:
                content = content[:max_file_chars]
                truncated = True

            # Redact secret-like patterns
            if redact_secrets:
                content = _redact_secrets(content)

            rel = str(fpath.relative_to(project_dir))
            tokens = estimate_tokens(content)
            file_fragments.append(FileFragment(rel, content, tokens))
            file_count += 1
            if truncated:
                logger.debug("Truncated %s to %d chars", rel, max_file_chars)
        except (OSError, PermissionError) as e:
            logger.warning("Could not read %s: %s", fpath, e)
            skipped_count += 1

    return ScanResult(
        tree=tree,
        file_fragments=file_fragments,
        skipped_count=skipped_count,
        excluded_patterns=all_exclude,
    )
