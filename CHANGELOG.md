# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to Semantic Versioning.

## [Unreleased]

## [0.4.2] - 2026-09-05

### Fixed

- **Release smoke tests now exercise the built wheel instead of the checkout.** Running the clean-venv commands from the repository root let local source files shadow the installed artifact, so a wheel missing modules or package data could pass validation (#77).
- **Source distributions no longer include local Claude session metadata.** Hatch's default sdist selection could package an untracked `.claude/handoff.md` from a maintainer's workspace; the build now excludes `.claude`, and the generated handoff is ignored by Git (#76).
- **`--max-output-tokens` now applies to pass 1 as well as pass 2.** Large directory trees could exhaust pass 1 at the hard-coded 128000-token default even when the CLI flag or `GRAPHLM_MAX_OUTPUT_TOKENS` raised the documented ceiling, so graph generation failed with an error recommending an override that the failing request ignored (#73).
- **Provenance tests no longer inherit the developer's GPG-signing configuration.** Their disposable repository commits could fail or prompt when global `commit.gpgsign=true`; synthetic setup commits now disable signing locally while real project commits remain signed (#74).

### Infrastructure

- **Release tags are now created only after the release PR and resulting `main` commit pass CI.** The documented `git push --follow-tags` flow could trigger irreversible PyPI publication before the release commit was tested; version bumps now edit files only, and maintainers push one verified signed tag after merge (#78).

## [0.4.1] - 2026-09-05

This patch makes `graphlm --upgrade` use the same installer that put this binary on PATH (`uv tool` / `uv pip` / pip / pipx).

### Fixed

- **`graphlm --upgrade` uses the same installer that installed this binary.** A `uv tool install` is upgraded with `uv tool upgrade` (from `uv-receipt.toml`, without following the `bin/python` symlink out of the venv). A `uv pip install` is upgraded with `uv pip install --upgrade`. pip stays `python -m pip`. 0.4.0 followed `bin/python` into uv's managed CPython, classified a uv-tool install as pip, and failed with `No module named pip` (#71).

## [0.4.0] - 2026-09-04

This release finishes the GitHub top-10 language packs (C#, C/C++, Go, PHP), adds a project `.graphlmignore` and `graphlm --upgrade`, and fixes the pass-2 edge table dropping on deep monorepos.

### Added

- **`graphlm --upgrade`.** Detects whether this binary came from `uv tool`, pipx, or pip, preserves extras (`mcp`, language packs), and upgrades to the latest PyPI release. A source checkout is refused (pull/`uv sync`, or install a release). Flag, not a subcommand, so `graphlm <project>` is unchanged (ADR-012).
- **`.graphlmignore`** — a project-level ignore file (gitignore-lite: one glob per line, `#` comments, blanks skipped) read from the scanned project root and merged into the scanner's exclude set, so a repo can record "always skip this worktree / cache / generated tree" instead of passing `--exclude` on every run. `--no-graphlmignore` opts out. The file itself is never sent to the model. Absent file is a no-op (#38).
- **PHP import edges via `graphlm[php]`.** `use App\Models\User` resolves to `App/Models/User.php` under `src/` roots. Quoted `require`/`include` of a string literal resolve relative to the importer (`kind` `include`). Concatenated `__DIR__ . "/x.php"` paths are dropped and mark the list not exhaustive. The grammar accessor is `language_php` (not `language()`). Without the extra: zero PHP edges, one log line, never a crash.
- **Go import edges via `graphlm[go]`.** `import "example.com/mod/pkg"` resolves to a package directory when **exactly one** non-test `.go` lives there (import path tried longest-first, then suffixes so a module prefix is optional). Multi-file packages are dropped (GRAPH_DIFF fan-out) and mark the list not exhaustive. `import "./rel"` is path-relative. `import "fmt"` is third-party, not partial. Without the extra: zero Go edges, one log line, never a crash.
- **C/C++ `#include` edges via `graphlm[cpp]`.** Quoted `#include "foo.h"` resolves relative to the importing file (with an extension probe). Angle-bracket system headers (`#include <stdio.h>`) are dropped as third-party; macro includes (`#include FOO`) mark the list not exhaustive. One extra pulls both `tree-sitter-c` and `tree-sitter-cpp` (``.c``/``.h`` vs ``.cpp``/``.hpp``/…). `kind` is `include`. Without the extra: zero C/C++ edges, one log line per language, never a crash.
- **C# import edges via `graphlm[csharp]`.** `using static Ns.Type` / `using Alias = Ns.Type` resolve to `Ns/Type.cs`. A namespace `using Ns;` resolves only when exactly one scanned file lives in that namespace directory — two or more files are dropped (same GRAPH_DIFF fan-out reason as Java wildcards) and mark the list not exhaustive. `using System;` and other misses are third-party, not partial. Without the extra: zero C# edges, one log line, never a crash.

### Fixed

- **Directory tree no longer restates the full relative path on every line.** The pass-1/pass-2 tree is an indented listing (`indent + basename`, directories end with `/`). Previously each line repeated the whole path *and* indented, so the 5000-line cap still overflowed `max_context` on deep monorepos — n8n's tree was ~151k tokens against a 131k window, every pass-2 file was truncated, and the AST edge table was dropped with `edge table dropped: header does not fit the 0-token edge budget`. The same tree is now ~72k tokens, the edge table fits, and if a tree still fills the budget the warning names that cause (parser edges still used for cycle detection). Pass 1 is told to reconstruct full paths from the indent when requesting files (#69).

## [0.3.1] - 2026-09-04

This patch stops graphlm from loading a scanned project's `.env` as its own LLM config.

### Fixed

- **LLM config no longer reads a project or working-directory `.env`.** graphlm used to search from cwd upward for a `.env` (#45) so an installed binary could pick up a per-project file. That also meant `graphlm .` inside a repo would load *that repo's* dotenv into the process — including any `GRAPHLM_*` keys it happened to define, and every other secret in the file. Settings now come only from the exported environment and `~/.config/graphlm/.env` (or `$XDG_CONFIG_HOME/graphlm/.env`). A scanned project's `.env` stays a never-read sensitive file, not graphlm's own config. If you configured graphlm via a project `.env`, move those values to the user-level file or export them (#65).

## [0.3.0] - 2026-09-04

This release adds opt-in Tree-sitter language packs so JavaScript/TypeScript, Java, and Rust repos get the same parser-proven import edges Python already had — without pulling grammar wheels into the base install.

### Added

- **JavaScript/TypeScript import edges via `graphlm[js]`.** Until now the scanner already packed `.js`/`.ts`/`.jsx`/`.tsx` files into the pass-2 prompt, but the Tree-sitter pass only extracted Python imports — so the model's claims about a TypeScript repo had no parser ground truth to check against. Installing the optional extra (`uv tool install 'graphlm[js]'`, or `graphlm[all]`) pulls the `tree-sitter-javascript` and `tree-sitter-typescript` wheels; graphlm then extracts `import` / `export … from` / `require()` / dynamic `import()` and resolves **relative** specifiers (`./foo`, `../bar`, including `index.*` barrels) against files that exist in the scan. Bare packages (`react`) are dropped, same rule as Python stdlib, and the pass-2 edge table is labelled *not exhaustive* so the model still infers them. The base install is unchanged: without the extra, a JS/TS repo yields zero parser edges and one log line per language, never a crash, and Python edges on a mixed repo stay intact. `.tsx` files use the TSX grammar (JSX in a `.ts` file is the wrong tree). `require()` edges use kind `require` so they stay distinct from ESM `import` in the graph-vs-graph diff.
- **Rust import edges via `graphlm[rust]`.** `mod foo;` becomes an `include` edge to `foo.rs` / `foo/mod.rs`; `use crate::` / `super::` / `self::` resolve against a filesystem module tree built from the scanned files (`lib.rs`/`main.rs` as crate roots). External crates (`use serde::…`) are dropped like Python stdlib. Inline modules and `#[path]` modules are skipped and mark the list not exhaustive rather than guessing a file. Without the extra: zero Rust edges, one log line, never a crash.
- **Java import edges via `graphlm[java]`.** Same opt-in-extra model as JS/TS: `import com.acme.User;` resolves to `<root>/com/acme/User.java` against files in the scan, with Maven/Gradle source roots (`src/main/java`, `src/test/java`) and the file's `package` declaration as a disambiguator. `import static Type.member` uses kind `static` so it stays distinct in the graph-vs-graph diff. Package wildcards (`import com.acme.util.*;`) are **dropped** — fanning them out would make adding one file to a package mutate every wildcard importer's edge set — and trip the non-exhaustive framing; `import static Type.*;` still resolves to `Type.java` because the class is known. Without the extra, Java files contribute zero parser edges and one log line, never a crash.

### Infrastructure

- `ci.yml` now sets an explicit read-only `permissions: contents: read` at the workflow level. Neither the test nor typecheck job writes anything (no releases, no PR comments, no checks API calls), so this is least-privilege, not a behavior change; addresses CodeQL's `actions/missing-workflow-permissions` finding.

### Docs

- README documents language packs as a first-class install table (`graphlm[js]` / `[java]` / `[rust]` / `[all]`), lists `GRAPHLM_BASE_URL` / `API_KEY` / `MODEL` as required (they have no built-in defaults), and points GitHub-wheel installs at the latest-releases page instead of a stale versioned URL. `.env.example` uses placeholders, not a specific host or model.

## [0.2.0] - 2026-09-03

This release is the output of an innovation pass over the codebase (`INNOVATIONS.md`): the map becomes queryable by agents over MCP, every run stamps its real token usage and an LLM-vs-parser faithfulness score, the map gets a native Mermaid picture, and oversized files are sent as signature skeletons instead of being cut off.

### Added

- **`graphlm --serve` — the map as an MCP server for coding agents.** Until now an agent had to read the whole `GRAPH.md` (tens of thousands of tokens) to answer one question like "who imports `scanner.py`?". `--serve` exposes the generated map over a stdio [MCP](https://modelcontextprotocol.io) server with eight typed, zero-LLM tools — `overview`, `find`, `module`, `neighbors`, `dependents` (blast radius, optionally transitive), `cycles`, `entry_points`, and `staleness` (stamped commit vs current `HEAD`) — each answering in a few hundred tokens. Import edges are unified from both sources and labelled `ast` (parser-proven), `llm` (inferred), or `both`, so an agent can weight them. The server reads `.graphlm/GRAPH.json` (or the `-o` directory), reloads it automatically when a regeneration lands, never calls the LLM, and reports a missing/corrupt map as an actionable tool error rather than a crash. The MCP SDK is an opt-in extra (`uv tool install 'graphlm[mcp]'`); the base install is unchanged, and using `--serve` without it prints the install hint. Register once per repo with `claude mcp add graphlm -- graphlm --serve /path/to/repo`. The `--install-skill` guide now tells the agent to prefer these tools when they are available. The query logic (`graphlm/query.py`) is a plain library surface too, usable without MCP.
- **Run telemetry in the stamp.** Every real run now records, in `GRAPH.json`'s `meta` block, (1) the endpoint's **real token usage** per pass — `prompt_tokens` / `completion_tokens` as the server counted them, stored beside graphlm's own `estimated_prompt_tokens` for the same prompt — and (2) a **faithfulness score**: how well the LLM's `import_edges` agree with the parser's `deterministic_edges` (precision = share of the model's Python import edges the parser confirms; recall = share of the parser's edges the model reproduced). Why it matters: the estimate-vs-real pair makes the `estimate_tokens` heuristic auditable per endpoint instead of guessed at, and the faithfulness score tells a reading agent how much to trust the LLM's edge table on *this* run — a low precision means the model invented dependencies the parser can't see. Both are summarised in one `> **Run telemetry.**` line directly under the refresh directive at the top of `GRAPH.md`, and echoed by the CLI as `Usage:` / `Faithfulness:` lines. Usage comes from `stream_options.include_usage` on the streamed request; an endpoint that doesn't report usage simply leaves the counts `null` ("not reported by endpoint"). The new `meta` fields are additive and optional — no `schema_version` bump, and a prior `GRAPH.json` without them still diffs normally. Not recorded on `--dry-run` (no LLM call) and faithfulness is absent under `--no-ast` (no ground truth).
- **Mermaid module graph in `GRAPH.md`.** The map now carries a picture, not only tables: a `## Module Graph` section right after the directory tree with a Mermaid `flowchart` of the import edges. GitHub (and most Markdown viewers) render Mermaid natively, so the diagram shows up in any repo that commits its map — no CDN, no separate file, works offline, unlike `GRAPH.html`. It draws the parser's Tree-sitter edges when present (labelled *ground truth*) and falls back to the LLM's edges under `--no-ast` (labelled *inferred*), so you always know which you are looking at. To stay legible it is **directory-level** — files collapse to their parent directory, root-level files stay their own node — and caps at 40 directories (highest-degree kept, with a "… N more directories not shown" note). Import-cycle members are drawn in red: edges whose endpoints share a cycle, plus a red outline on any directory containing a cycle member so a cycle inside one package (the common case, which collapses to nothing at directory level) is still visible. Output is sorted, so a regenerated map diffs cleanly
- **Ground-truth layers in `GRAPH.html`.** The interactive graph now draws the parser's `deterministic_edges` as a distinct solid-blue "Parser imports" layer alongside the grey LLM imports and the dashed data flow, with a **Layers** control (three checkboxes) to show or hide each. Every node that is part of an import cycle gets a red ring and a "Member of an import cycle" line in its tooltip. Where the LLM reported the same edge the parser found, only the parser's line is drawn (the duplicate is dropped and the AST link marked *corroborated* in the embedded data), so one relationship is never two lines. The legend and the stats line (edges broken down by parser / LLM / data flow, plus the cycle count) reflect the new layers

### Changed

- Oversized Python files are now sent to the LLM as a **tree-sitter signature skeleton** instead of their first 4000 characters. Previously a file longer than `--max-file-chars` was cut at the cap, so for a 1500-line module the model saw the imports and the first class and nothing else — its `file_summaries`, `symbols`, `entry_points` and `quick_reference` entries for big files were guesses. The skeleton keeps every import, every class/def signature (decorators, multi-line headers, return annotations), the first line of each docstring, and short constants, with bodies elided to `...` and long constants collapsed to `NAME = {…}  # N lines elided`. It is exact where the head was partial, and smaller: on graphLM's own tree the same 80 pass-2 files pack into ~12% fewer estimated tokens (`--no-skeleton` ~73.0k → ~64.1k) while carrying every symbol. The skeleton starts with a `# [graphlm skeleton: …]` marker and the pass-2 prompt tells the model to summarize the API from it and not invent behaviour for elided bodies. Secret redaction still runs on the skeleton (docstring lines and constants can hold secrets). Python only for now — other languages still send the head. `--no-skeleton` / `skeleton=False` restores head-truncation.
- `graphlm/redact.py` now holds the secret handling relocated verbatim from `scanner.py`: the never-read extension/name lists with `_is_sensitive_file`, and the redaction regexes (`_redact_secrets`). The scanner re-imports both, so every candidate file is still screened and every fragment still passes through redaction — the security invariants are unchanged; the move only keeps `scanner.py` under the module size limit.

### Fixed

- Nested git checkouts inside the scanned project — a worktree, a submodule, or a vendored clone (anything whose directory holds a `.git` file or directory) — were scanned as if they were part of the project, so every module and import edge under them was duplicated into the map under a second path prefix (observed with agent worktrees under `.claude/worktrees/`). The scanner now treats such a subtree as a separate project and leaves it out of both the pass-1 tree and the file walk; the scan root itself is unaffected.
- `GRAPH.html` showed only the LLM's edges and never highlighted cycles. The map's *verified* structure — the Tree-sitter import edges and the Tarjan import cycles with risk scores — was computed and written to `GRAPH.md`/`GRAPH.json` but never reached the picture, so the interactive view could contradict the ground-truth table beneath it and gave no visual cue for the cycles the report called out. Both now render (see Added above)
- Import-cycle risk scores under-weighted large files. The `log10(total_lines)` term counted the lines of the *truncated* fragment (cut at `--max-file-chars`), so a 1500-line module in a cycle scored as a ~100-line one — exactly the file a risk score should weigh most. `FileFragment` now carries the real on-disk `line_count`, captured before any truncation or skeletonisation, and cycle scoring uses it.
- `--dry-run` reported `0 import edges` on every run. That figure was `len(graph.import_edges)` — the **LLM's** field, which a dry run never fills — so it always read 0 and looked like "no imports found" even on a project the parser had fully resolved. The stats now show `AST import edges: N` from the parser's `deterministic_edges` (`AST off` under `--no-ast`), and the misleading LLM-field count is gone from the dry-run line.

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

[Unreleased]: https://github.com/ggrace519/graphLM/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/ggrace519/graphLM/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/ggrace519/graphLM/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/ggrace519/graphLM/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/ggrace519/graphLM/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/ggrace519/graphLM/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ggrace519/graphLM/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/ggrace519/graphLM/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/ggrace519/graphLM/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ggrace519/graphLM/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ggrace519/graphLM/releases/tag/v0.1.0
