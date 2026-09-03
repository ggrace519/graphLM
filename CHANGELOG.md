# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to Semantic Versioning.

## [Unreleased]

### Changed

- Oversized Python files are now sent to the LLM as a **tree-sitter signature skeleton** instead of their first 4000 characters. Previously a file longer than `--max-file-chars` was cut at the cap, so for a 1500-line module the model saw the imports and the first class and nothing else — its `file_summaries`, `symbols`, `entry_points` and `quick_reference` entries for big files were guesses. The skeleton keeps every import, every class/def signature (decorators, multi-line headers, return annotations), the first line of each docstring, and short constants, with bodies elided to `...` and long constants collapsed to `NAME = {…}  # N lines elided`. It is exact where the head was partial, and smaller: on graphLM's own tree the same 80 pass-2 files pack into ~12% fewer estimated tokens (`--no-skeleton` ~73.0k → ~64.1k) while carrying every symbol. The skeleton starts with a `# [graphlm skeleton: …]` marker and the pass-2 prompt tells the model to summarize the API from it and not invent behaviour for elided bodies. Secret redaction still runs on the skeleton (docstring lines and constants can hold secrets). Python only for now — other languages still send the head. `--no-skeleton` / `skeleton=False` restores head-truncation.
- `graphlm/redact.py` now holds the secret-redaction regexes (`_redact_secrets`), relocated verbatim from `scanner.py`; the scanner re-imports it, so every fragment still passes through redaction and existing imports keep working.

### Fixed

- Import-cycle risk scores under-weighted large files. The `log10(total_lines)` term counted the lines of the *truncated* fragment (cut at `--max-file-chars`), so a 1500-line module in a cycle scored as a ~100-line one — exactly the file a risk score should weigh most. `FileFragment` now carries the real on-disk `line_count`, captured before any truncation or skeletonisation, and cycle scoring uses it.

### Fixed

- Nested git checkouts inside the scanned project — a worktree, a submodule, or a vendored clone (anything whose directory holds a `.git` file or directory) — were scanned as if they were part of the project, so every module and import edge under them was duplicated into the map under a second path prefix (observed with agent worktrees under `.claude/worktrees/`). The scanner now treats such a subtree as a separate project and leaves it out of both the pass-1 tree and the file walk; the scan root itself is unaffected.

## [0.1.3] - 2026-08-31

### Fixed

- `--dry-run` mislabeled its file count. The line read `Files scanned: N`, but `N` was the number of files **selected for pass-2 analysis** (capped at `--max-pass2-files`, default 80), not the number of files scanned (bounded by `--max-files`, default 200). On any project with more than 80 source files the two differ, so the label under-reported the scan and read as a smaller repo than was actually walked. The line now reads `Files selected for pass-2 analysis: N`.
- Config from a `.env` file was silently ignored for installed users (#45). `config.py` loaded `.env` with a bare `load_dotenv()`, which searches upward from the *package's own directory* — so once graphLM was `uv tool install`ed, it looked next to its site-packages install, never at the project you were mapping. Two consequences, both fixed: (1) a **project `.env`** is now found from the **current working directory** upward (`find_dotenv(usecwd=True)`), so it works from an installed graphLM, not only from a source checkout; and (2) a new **user-level fallback** at `~/.config/graphlm/.env` (or `$XDG_CONFIG_HOME/graphlm/.env`) lets you configure an installed graphLM once instead of dropping a `.env` in every project. Precedence, first non-empty wins: exported shell env > project `.env` (cwd upward) > user-level `.env` > built-in defaults; higher sources are never clobbered. (Running with the repo as your working directory is unchanged.)

### Docs

- Design docs for multi-language AST support (#42): `docs/plans/multi-language-support.md` (research + recommendation) and `docs/plans/multi-language-implementation.md` (phased build plan). No code change yet — this is the approved design for adding deterministic import-edge extraction beyond Python. Model: **Python is the only core language** (the sole grammar in the base install); every other language is an **opt-in pip extra** (`graphlm[js]`, `graphlm[java]`, `graphlm[rust]`, `graphlm[all]`) with a bundled, graphlm-authored resolver — no third-party plugin API. Planned packs, in build order: JS/TS, Java, Rust.

### Infrastructure

- Release automation via [bump-my-version](https://github.com/callowayproject/bump-my-version) (`[tool.bumpversion]` in `pyproject.toml`). `uvx bump-my-version bump patch|minor|major` now bumps the version, promotes the `[Unreleased]` changelog section to a dated release header, updates the compare links, and makes a GPG-signed commit + signed tag — the mechanical release steps that were done by hand. `uv lock` and `git push --follow-tags` remain manual. See the "Releasing" section in `CONTRIBUTING.md`

## [0.1.2] - 2026-08-31

Maintenance release: `--install-skill` guide refinements from testing it across
Claude, Codex, and Grok on a real repo.

### Changed

- `--install-skill` guide improvements, from testing it across Claude, Codex, and Grok:
  - **Stronger trigger.** The skill `description` now tells the agent to reach for the map at the **start** of working in a codebase — before reading or searching through files — rather than only when explicitly asked. This is safe now that the guide handles an unmapped repo gracefully (it no longer risks a mid-task stall).
  - **Data-egress heads-up.** The guide now notes that `graphlm .` **sends selected repository code to the configured LLM endpoint** (`GRAPHLM_BASE_URL`). It still generates without stalling for a local/trusted endpoint, but says to surface the destination and get a quick OK when the endpoint is a third-party API — so a private codebase isn't exported silently. (A Codex safety layer flagged exactly this.)
  - Reinstall the updated guide with `graphlm --install-skill claude --skill-force`.

## [0.1.1] - 2026-08-31

Maintenance release: a fix to the `--install-skill` agent guide, plus the
community-health docs and role-address contact change made after 0.1.0 shipped.

### Changed

- `--install-skill` guide now distinguishes the two invocation modes so an agent doesn't stall or misfire. When it's invoked **explicitly** (the user ran the skill/command directly) and no map exists, the guide says to generate one with `graphlm .` **without asking** — a safe, local, idempotent action — then read and summarize it. When the skill is **reached for mid-task**, it says *not* to generate (a fresh generation streams for a minute or two and would stall the user's real request) — just read an existing map, or note in one line that none exists. Fixes an agent freezing into a "what do you want to do?" menu when the skill was run in a repo with no map. Reinstall the updated guide with `graphlm --install-skill claude --skill-force`
- Package author contact is now a role address (`graphlm@519lab.com`) instead of a personal one, and the Code of Conduct routes to `conduct@519lab.com`. (v0.1.0's PyPI metadata carried the old address; a published version's metadata can't be edited, so this takes effect from the next release.)

### Added

- Community-health docs for the now-public repo: `CONTRIBUTING.md` (dev setup, the real test/mypy commands, branch/PR/commit conventions, and the security invariants contributors must not weaken), `SECURITY.md` (private vulnerability reporting via GitHub's advisory flow, with an in/out-of-scope threat model given graphlm reads untrusted code), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), a PR template with a verification checklist matching this repo's conventions, and issue forms (bug / feature) that route security reports away from public issues. README gained Contributing and Security sections

## [0.1.0] - 2026-08-30

First public release. graphlm is installable from PyPI (`uv tool install graphlm`
/ `pipx install graphlm`) and from the attached GitHub Release artifacts; the
`graphlm` command lands on your PATH. Everything below shipped in 0.1.0.

### Added

- **Packaged for release**: published to PyPI and GitHub Releases from a single
  git tag via a Trusted-Publishing workflow (`.github/workflows/release.yml`) —
  no stored API token. The release build installs the wheel into a clean venv
  and smoke-tests `graphlm --version` + a `--dry-run` before publishing, so a
  missing entry point, data file, or dependency fails the release instead of
  reaching users
- `--version` / `-V` flag: prints the installed graphlm version and exits
- `--install-skill <harness>` flag: drops a guide that teaches a coding agent how
  to use graphlm and to look for its map (`.graphlm/GRAPH.md`) when loading a
  codebase — regenerating it with `graphlm .` when absent or stale. Targets
  `claude` (writes `~/.claude/skills/graphlm/SKILL.md`) and `codex` (writes
  `~/.codex/graphlm.md` and prints a one-line snippet to include from your own
  `AGENTS.md`). Installs user-global by default (`--skill-local` writes into the
  scanned project instead); idempotent (skip-if-exists unless `--force`). It only
  ever creates graphlm's own files — it never edits your existing `CLAUDE.md` /
  `AGENTS.md`, and it refuses to write *through* a symlink at the target (so a
  dotfiles-managed `~/.claude/skills/` can't be clobbered) (#33)
- **Self-refreshing graph**: every generated `GRAPH.md` now carries a top-of-file *provenance & refresh directive*, and `GRAPH.json` a versioned `meta` block, recording when the map was generated and against which git commit. A coding agent reading `GRAPH.md` can compare the repo's current `HEAD` to the stamped commit and regenerate (`graphlm .`) when they differ — the agent is the scheduler; graphlm adds no hook, flag, or staleness logic of its own. Non-git projects degrade gracefully (no SHA; the directive falls back to the agent's judgment). The directive is advisory. Wording is deliberately "generated against commit X" (not "reflects X") because the map is built from files on disk, which may include uncommitted changes — a graph can be SHA-fresh yet not match the working tree
- **Graph-vs-graph diff (`GRAPH_DIFF.md` / `GRAPH_DIFF.json`)**: every real run now also writes a structural diff of the map — modules, import edges (LLM and AST), import cycles, data flows, entry points, and file summaries **added and removed** since the prior `GRAPH.json`. This answers "what changed in the map since last time?" at a glance (a new entry point, a dropped module, a broken/added import cycle) without re-reading the whole graph. It reads graphlm's *own* prior output — which is why the `meta` block was made a versioned input contract. It is **not** a code diff (git does that better): added/removed only, so a pure prose rewrite (a description, a summary) is intentionally invisible; renames show as remove+add (no rename heuristics). Three baseline states are always distinguished so an agent can tell them apart: *first run* ("initial graph — no prior version"), *uncomparable* (a corrupt or unrecognized-`schema_version` prior file — never masqueraded as a first run), and *normal*. The diff header carries the old→new commit-SHA range. Toggling `--no-ast` between runs does not fabricate a mass edge deletion (the AST dimension reports "not compared" when either side skipped AST). On by default; `--no-diff` / `include_diff=False` opts out. `--dry-run` writes no diff (it produces no authoritative graph). No new network or LLM call — pure local computation over the two graphs (#28, ADR-002)
- `--timeout` CLI flag / `GRAPHLM_TIMEOUT` env var to configure the LLM request timeout (default raised to 300s). Resolves `--timeout` > `GRAPHLM_TIMEOUT` > 300, mirroring `--max-context` (#18)
- `--max-output-tokens` CLI flag / `GRAPHLM_MAX_OUTPUT_TOKENS` env var to configure the graph output-token ceiling. Defaults to the model's practical max (128000) so large graphs don't truncate; it is a request ceiling only (the model stops when done), independent of the input budget (#18, #25). Raise it only on an endpoint that bounds input+output together
- Streaming LLM responses: `call_llm` now sends `stream: true` and reassembles the SSE deltas. This keeps a long generation alive past proxy read-timeouts and adds a clear "output truncated (hit max_tokens)" error instead of a confusing parse failure. A server that ignores the flag and returns a buffered body is handled transparently (#18)
- Two-pass LLM strategy: pass 1 sends directory tree only to identify key files, pass 2 sends tree + selected files for full analysis
- CLI tool via Typer with `--dry-run`, `--no-tests`, `--exclude`, and `--max-files` options
- Library API via single `generate_graph()` function returning `GraphResult`
- Pydantic v2 models for structured graph data (import edges, modules, data flow, DB schema, test mapping, architecture notes, quick reference)
- Project scanner with smart file ranking (config files > package init > source > tests)
- Token estimation heuristic (~4 UTF-8 bytes per token)
- LLM client with JSON recovery (strips code fences, finds braces in text)
- Retry logic with exponential backoff on connection errors
- Markdown and JSON output rendering
- System prompt with injection guard (treats file content as data only)
- Test fixtures: small, medium, and large project directories
- Tree-sitter-based AST parser for deterministic import/edge extraction (Python, JS, TS)
- `--ast` CLI flag: enables AST-derived deterministic import edges alongside LLM analysis
- Import cycle detection via Tarjan's SCC algorithm with risk scoring based on module size and cycle length
- `--no-show-cycles` / `--cycle-threshold` CLI flags for cycle control
- Interactive D3 force-graph HTML visualization output with zoom/pan, hover tooltips, click highlighting, search, and dark/light mode
- `--no-html` CLI flag (HTML enabled by default)
- New `deterministic_edges` and `import_cycles` fields on `CodebaseGraph` model

### Changed

- CLI writes its output into a **`.graphlm/` subdirectory of the scanned project** by default (not the process working directory, and no longer the project root) — so `GRAPH.md` / `GRAPH.json` / `GRAPH.html` / `GRAPH_DIFF.*` stay out of the way in one tidy folder. `-o <dir>` still overrides and is honored literally (no `.graphlm` appended). The whole `.graphlm/` directory is excluded from scanning, so a re-run never ingests its own map. Note the map now lives at `.graphlm/GRAPH.md`; agents/tooling looking for `GRAPH.md` at the project root should look in `.graphlm/`. The library API is unchanged — `generate_graph(output_dir=...)` / `result.write(dir)` still write to the literal directory given
- Output files are `GRAPH.md`, `GRAPH.json`, and `GRAPH.html` (were `graphs.md` / `graphs.json` / `graph.html`)
- AST import parsing is on by default; pass `--no-ast` or `ast=False` to skip. The `--ast` flag is removed
- `GraphResult.write()` / `write_outputs()` now return a `WriteResult` — the `(md, json, html_or_none)` 3-tuple you can still unpack three ways, now carrying `.diff_md` / `.diff_json` attributes for the graph diff (#28). (This supersedes the earlier `tuple[Path, Path, Path | None]` return added with HTML; the positional arity is unchanged, so `md, json, html = result.write(...)` keeps working)
- `write_outputs()` now optionally writes HTML alongside Markdown and JSON

### Fixed

- graphlm produced **no graph at all** against a served model that needs a structured-output constraint (its own default Qwen endpoint): pass 2 relied on prompt-only instruction to make the model emit a `CodebaseGraph`, but never sent a `response_format` in the request. `Qwen3.6-35B` returned a near-empty `{"database_schema": null}` and the run failed with a schema-validation error, writing nothing. Pass 2 now sends `response_format: {type: json_schema}` (gated on a structured response being requested, so pass 1's free-form file-list request is untouched). The endpoint treats it as a guided-JSON hint, so the prompt's "return an empty directory_tree" and the locally-filled `meta`/`import_cycles`/`deterministic_edges` still come back empty — #18 is not reopened. Endpoints that reject the parameter (HTTP 400) fall back once to prompt-only, so a prompt-following endpoint still works; 401/403/404/429 still surface as errors. Verified end-to-end against the live Qwen endpoint (was invisible to CI, which mocks the LLM) (#31)
- graphlm ingested its own output on a re-run: `GRAPH.md` / `GRAPH.json` / `GRAPH.html` sit in the scanned directory but were never excluded, so a second run over an already-mapped project fed its own previous map into the LLM as source. These artifacts (and the new `GRAPH_DIFF.*`) are now always excluded from scanning. The exclusion is by exact name, not a broad `GRAPH*` glob, so a user's `GRAPHICS.md` / `GRAPHING.md` etc. are untouched (#28)
- Sensitive-file read gap: arbitrary `.env.<name>` files (e.g. `.env.qa`, `.env.test`) were scanned into LLM context because the sensitive-file check used a fixed allowlist. Any dotenv file is now treated as secret-bearing, except the non-secret templates `.env.example` / `.env.sample` / `.env.template` / `.env.dist` (#10)
- `GRAPHLM_MAX_CONTEXT` had no effect: it was parsed into `Settings` but never read, so the pass-2 context budget was always 120000. The budget now resolves as `--max-context` flag > `GRAPHLM_MAX_CONTEXT` env var > 120000 (#11)
- Pass-2 prompt could exceed `max_context` (#12): per-file admission respected the budget, but the AST-edge table was appended uncapped and the instruction block was never counted, so a project with many import edges produced an over-budget prompt (a 6000-edge table alone reached ~62k tokens regardless of the budget). Now every fixed section is reserved up front and the edge table is capped at a bounded share of the budget; when the table is truncated, its framing changes to tell the model the list is not exhaustive so it still infers the dropped edges. The full edge list is unaffected — it still reaches `graph.deterministic_edges` and cycle detection. Also removes spurious truncation of files that would have fit
- External symlinked *files* pointing outside the project were listed in the directory tree and consumed a `max_files` slot (only symlinked directories were guarded). Any symlink escaping the project is now skipped in the tree walk; file content was already blocked before reading
- The deterministic AST import graph came back **empty on real Python projects** (0 edges, 0 cycles), silently — the LLM's inferred edges masked it (#19). Two compounding causes: (a) file ranking gave documentation the same priority as source, so on a doc-heavy repo (argus: 91 `.md` vs 135 `.py`) markdown crowded source out of the `max_files` scan, and edges only resolve between *scanned* files — source now outranks non-source text; (b) src-layout projects (package under `src/`) import by package name (`from mypkg.core import X`) but the scanned file is `src/mypkg/core.py`, so no candidate matched — the resolver now derives source-root prefixes (`src/`, …) from the scan and tries each. argus went from 0 to 342 deterministic edges; root-layout projects are unchanged (root `""` is tried first)
- graphlm overflowed the LLM context on large / polyglot / build-heavy repos, failing with an upstream "Context size has been exceeded" error and producing no graph at all (#17). Two compounding causes, both measured against the real model server: (1) the **pass-1 directory tree was unbounded** — `max_files` capped only the files *read* in pass 2, never the tree, and `_ALWAYS_EXCLUDE` missed the big build/cache dirs (`target/`, `.hypothesis/`, `dist/`, `build/`, `.ruff_cache/`, `.next/`, `coverage/`, …), so a repo's tree alone could reach ~400 KB / ~140k tokens; (2) the **token estimate under-counted by ~28%** — `estimate_tokens` assumed 4 bytes/token but real tree+code content measures ~2.83, so a "within budget" prompt actually ran far over. Fixes: the exclude set now covers the common build/cache dirs; the tree is bounded by a per-directory cap (200 listed children, spread so nested source stays visible) plus an absolute 5000-line total ceiling; and `estimate_tokens` is recalibrated to ~2.5 bytes/token (over-estimating so the budget is a real guarantee) and unified into a single implementation (was duplicated in `scanner.py` and `context.py`). Verified end-to-end: a repo that overflowed now assembles a pass-1 prompt ~8× smaller and completes pass 1 in well under the context window
- Pass 2 on a large project failed to produce a graph, in two stages, both fixed under #18:
  - **Transport (HTTP 524):** after the context-overflow fix, the model's full-graph generation legitimately took >120s and the non-streamed request died at Cloudflare's edge read-timeout while the origin was still generating. The response is now streamed, which resets that timeout on every delta, and the client timeout default is raised to 300s (configurable via `--timeout` / `GRAPHLM_TIMEOUT`). Measured: a generation that 524'd at ~125s buffered now completes in ~200s streamed.
  - **Output truncation:** the graph was cut off mid-generation because the model's output exceeded the 16000-token `max_tokens` ceiling. Two compounding causes: (a) the pass-2 prompt told the model to *echo the entire directory tree* back inside its JSON (~20k output tokens for the argus tree — invariant to `--max-pass2-files`, since tree size doesn't depend on file count); the model is now told to return an empty `directory_tree` and `generate_graph` fills it from the scan locally (it already has it). (b) even without the echo, a real project's analysis needs more than the old 16000-token ceiling; the ceiling is now configurable (`--max-output-tokens` / `GRAPHLM_MAX_OUTPUT_TOKENS`) and defaults to the model's practical max (see #25). A response that still hits the ceiling now raises a clear "graph too large — raise --max-output-tokens" error instead of a confusing parse failure.
- The output ceiling was needlessly capped low **and** was double-counted against the input budget (#25). graphlm reserved `max_output_tokens` out of `max_context` on the assumption that input and output share one context window — **false on the target endpoint** (measured: 180k input + 200k `max_tokens` = 380k combined is accepted). Fixes: (1) the output ceiling defaults to the model's practical max (128000) so large graphs don't truncate — it's a request ceiling, not a reservation, so a high value is free; (2) input file admission no longer subtracts the output budget, only a small message-overhead reserve, which raises effective input capacity by ~38% (more files analyzed per run). The pass-2 output reserve and the requested `max_tokens` are no longer coupled. Endpoints that *do* bound input+output together (vLLM, Anthropic) can lower `--max-output-tokens`.
- `--max-output-tokens` help text was stale: it still said the default was 32000 and that the value "reserves that much of the pass-2 context" — both untrue since #25/#26 (default is 128000; the ceiling is independent of the input budget). Corrected in the CLI help and `CLAUDE.md`

### Changed

- `--max-context` CLI flag now defaults to unset (falls back to `GRAPHLM_MAX_CONTEXT`, then 120000) instead of a hardcoded 120000, so the env var is honored
- HTML threw `TypeError: e is not iterable` on load: D3 v7 `scaleOrdinal(null, palette)` iterates a null domain; use `scaleOrdinal(palette)` as the range
- HTML visualization did not initialize: `initGraph` was never called on page load, and a recursive self-call could hang the page
- `--ast` computed import edges then discarded them; cycle detection ran on LLM edges without SLOC-based risk scores
- `--no-html` still wrote `graph.html` when `-o` was set (HTML was written twice)
- `result.write()` returned three paths but the README unpacked two; string output paths failed
- AST import resolver mapped packages to non-existent `pkg.py` files and stdlib modules to `os.py`
- LLM copied test-fixture database schemas into the host project graph

### Infrastructure

- Python 3.11+ with hatchling build, uv dependency management
- pytest-httpx for mock HTTP integration testing
- pytest + coverage in CI
- `.env.example` for LLM endpoint configuration
- GitHub Actions CI testing on Python 3.11, 3.12, 3.13 with coverage upload to Codecov
- mypy type checking in CI
- Removed stale generated artifacts (`graphs.md`, `graphs.json`, `graph.html`) left over from before the `GRAPH.*` output rename, and the committed `.coverage` database; the repo no longer ships tool output. Added `.coverage`, `coverage.xml`, and the `GRAPH.*` output files to `.gitignore` so generated artifacts stay out of version control

[Unreleased]: https://github.com/ggrace519/graphLM/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/ggrace519/graphLM/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/ggrace519/graphLM/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ggrace519/graphLM/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ggrace519/graphLM/releases/tag/v0.1.0
