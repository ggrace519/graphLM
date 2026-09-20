"""Secret handling for scanned files: the never-read list and content redaction.

Both halves were relocated verbatim from ``scanner.py`` (the patterns are
unchanged) so the scanner stays under the module size limit once it grew
skeletonisation and the nested-checkout guard. ``scan_project`` re-imports
``_is_sensitive_file`` and ``_redact_secrets`` from here, so every candidate
file is still screened and every fragment still passes through redaction —
the security invariants live in ``scan_project``, not in where the patterns
are defined.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path


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
        r'(?i)((?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,})',
        r'[REDACTED:GITHUB_TOKEN]',
        redacted,
    )

    # Generic bearer / API key assignments (JSON `"api_key": "…"` too)
    redacted = re.sub(
        r'(?i)(["\']?(?:api[_-]?key|apikey)["\']?\s*[=:]\s*)["\']?([A-Za-z0-9_\-/+=]{20,})["\']?',
        r'\1"[REDACTED:API_KEY]"',
        redacted,
    )

    # Whole PEM block (headers + body). Header-only left the body in JSON
    # `"private_key": "-----BEGIN …\\nMIIE…\\n-----END …"`.
    redacted = re.sub(
        r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'
        r'.*?'
        r'-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
        r'[REDACTED:PRIVATE_KEY]',
        redacted,
        flags=re.DOTALL,
    )
    # Leftover header lines if the block was truncated.
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

    # Password assignments (KEY = value, including JSON `"password": "…"`)
    redacted = re.sub(
        r"(?i)([\"']?(?:password|passwd|pwd)[\"']?\s*[=:]\s*)([\"']?)(?!none|null|false|true|''|\"\"|\$\{)"
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

    # Long random-looking strings assigned to secret-ish names (`=` or JSON `:`)
    redacted = re.sub(
        r'(["\']?(?:secret|token|key|password|credential|auth)[^\s"\'=:]*["\']?\s*[=:]\s*)'
        r'["\']?([A-Za-z0-9_\-/+=]{32,})["\']?',
        r'\1"[REDACTED:SECRET]"',
        redacted,
        flags=re.IGNORECASE,
    )

    return redacted


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
    ".env",
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
    "*secret*",
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

# Source-code extensions exempt from the name patterns above (token.py is code).
_SOURCE_EXTS_FOR_SECRET_NAMES = {".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".h", ".hpp", ".cc", ".cxx", ".hh", ".hxx", ".php"}

# OpenSSH private-key filenames (no extension). `id_rsa.pub` is a public key
# and is not in this set. The `*private*` name glob misses these because the
# stem is `id_rsa`, not `private_key`.
_SSH_PRIVATE_KEY_NAMES = {
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_ecdsa_sk",
    "id_ed25519_sk",
}

# Credential files whose secret is not `password = ...` (so redaction misses
# them) and whose names miss the *password* / *token* globs.
_CREDENTIAL_FILE_NAMES = {
    ".netrc",
    "_netrc",
    ".pgpass",
    ".htpasswd",
}

# Exact never-read names that also have editor/suffix backups (`.bak`,
# `~`, `#name#`). `.env*` is handled separately (prefix rule).
_EXACT_SECRET_NAMES = (
    _SSH_PRIVATE_KEY_NAMES | _CREDENTIAL_FILE_NAMES | {".flaskenv"}
)


def _is_named_or_backup(lname: str, bases: set[str]) -> bool:
    """Exact never-read name, or a backup of one.

    Matches ``base``, ``base.bak`` / ``base.old``, ``base-orig``,
    ``base~``, ``#base#``. ``id_rsa.pub`` is excluded by the ``.pub``
    guard so public keys stay scannable.
    """
    if lname in bases:
        return True
    if lname.endswith(".pub"):
        return False
    for base in bases:
        if (
            lname.startswith(base + ".")
            or lname.startswith(base + "-")
            or lname == base + "~"
            or lname == "#" + base + "#"
        ):
            return True
    return False


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

    # Any file whose name is `.env` or starts with `.env` is secret-bearing
    # (`.env.local`, `.envrc`, vim `.env~`, `.env-local`), except templates
    # `.env.example` / `.sample` / `.template` / `.dist`. Requiring `.env.`
    # as the next character missed editor backups and hyphen/underscore
    # suffixes.

    if path.name.lower() in _SSH_PRIVATE_KEY_NAMES:
        return True
    # Backups: id_rsa.bak, id_ed25519.old, vim id_rsa~, emacs #id_rsa#.
    # Exact-name matching missed these and redaction only strips BEGIN/END,
    # leaving the key body.
    lname = path.name.lower()
    # Exact names plus editor/suffix backups. Redaction misses netrc
    # (`password SECRET`) and pgpass (`host:port:db:user:SECRET`), so
    # backups of those files must never be read either.
    if _is_named_or_backup(lname, _EXACT_SECRET_NAMES):
        return True

    # Any dotenv file (.env, .env.<anything>) is secret-bearing, except the
    # non-secret template variants. A fixed allowlist (_SECRET_EXTS) missed
    # arbitrary variants like .env.qa / .env.test; this catches them all.
    name = path.name.lower()
    if name == ".env" or name.startswith(".env"):
        if name.startswith(".env."):
            env_suffix = name[len(".env.") :]
            if env_suffix not in _ENV_SAFE_SUFFIXES:
                return True
        else:
            return True
    # `config.env` / `foo.env.local` — not a leading `.env`.
    if name.endswith(".env") or ".env." in name:
        if not any(name.endswith(".env." + s) for s in _ENV_SAFE_SUFFIXES):
            return True

    if name == ".flaskenv":
        return True

    stem = path.stem.lower()
    # Only apply name-based patterns to non-source files
    if suffix not in _SOURCE_EXTS_FOR_SECRET_NAMES:
        for pattern in _SECRET_NAME_PATTERNS:
            if fnmatch.fnmatch(stem, pattern) or fnmatch.fnmatch(path.name.lower(), pattern):
                return True
    return False


def _is_nested_checkout(dir_path: Path) -> bool:
    """True if ``dir_path`` is the root of another git checkout.

    A git worktree or submodule marks its root with a ``.git`` *file* (a
    pointer into the parent's gitdir), a vendored clone with a ``.git``
    directory; ``exists()`` covers both. Such a subtree is a different project
    — merging it into the parent's map duplicates every module and edge under a
    second prefix (observed with agent worktrees under ``.claude/worktrees/``
    and would equally hit submodules). The scan root itself is never tested
    here (only children are), so scanning a repo is unaffected.
    """
    try:
        return (dir_path / ".git").exists()
    except OSError:
        return False
