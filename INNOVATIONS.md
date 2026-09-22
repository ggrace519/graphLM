# Innovation Proposals — graphlm
*Generated 2026-09-02 · based on commit `692d819` (v0.1.3)*

## How this codebase stands today

graphlm is a ~3.9k-line Python CLI/library (Typer, httpx, Pydantic v2,
tree-sitter 0.26) that turns a repo into a codebase map — `GRAPH.md`, `GRAPH.json`,
a D3 `GRAPH.html`, and a `GRAPH_DIFF.*` — using a two-pass LLM strategy plus a
deterministic Tree-sitter import graph as ground truth. It is public on PyPI,
has 404 fast tests, clean mypy, three ADRs, and unusually honest docs about its
own limits. Its primary *consumer* is a coding agent: `--install-skill` teaches
Claude Code / Codex to read `.graphlm/GRAPH.md` before exploring a repo.

What it does well: context-budget discipline (measured token ratios, two tree
caps, exact prompt budgeting), security posture (never reads secrets, redacts,
blocks symlink escapes), provenance + structural diff, and a clean
registry seam for language packs (Phase 0 of #42 done; JS/TS pack is next and
has its own handoff — **not re-proposed here**).

Where it is ordinary, verified in the code:

- The agent-facing surface is one flat Markdown file. An agent must load the
  whole ~30–60k-token map to answer "who imports X?" — there is no query API.
- The AST parser extracts functions, classes, and call sites
  (`parsers/python.py::_parse_file_python`) but **nothing consumes them**; only
  imports feed the pipeline. The LLM is asked to invent the symbol table from
  4000-char fragments.
- Large files are truncated **head-only** at `max_file_chars` (`scanner.py:614`),
  so the model sees the imports and the first class of a 1500-line module and
  nothing else.
- Pass 1 (which files to read) is a paid LLM call with no deterministic
  fallback; the AST graph already exists before pass 1 runs but is not used to
  rank files.
- Every run regenerates the whole graph (~200s, tens of thousands of tokens)
  even when one file changed — despite already carrying a SHA stamp and a diff.
- The HTML view draws only the LLM's `import_edges` and `data_flow`
  (`html_render.py::_build_links`); the AST ground truth and the detected
  cycles never reach the picture. `--dry-run` prints `0 import edges` because
  it reports the (empty) LLM field, not the AST edges it just computed —
  the Phase 1 handoff even warns contributors not to trust that number.
- Cycle risk scores use line counts of the *truncated* fragment
  (`cycles.compute_sloc_map`), so every big file in a cycle is under-weighted.

## What the best in this space are doing

- **Aider's repo map** builds a file graph from tree-sitter `tags.scm`
  definitions/references, runs PageRank (personalised toward files in the chat),
  and binary-searches the ranked symbol list into a token budget, rendering only
  the definition lines with AST-aware context. Key weights: `_private` idents ×0.1,
  identifiers defined in >5 files ×0.1, compound names ≥8 chars ×10, refs
  square-rooted. ([repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py),
  [docs](https://aider.chat/docs/repomap.html)). The `tags.scm` it relies on
  **ships inside the `tree-sitter-python` wheel graphlm already installs**
  (`tree_sitter_python/queries/tags.scm`, verified locally).
- **Repomix `--compress`** uses tree-sitter to strip bodies and keep imports,
  signatures, classes and interfaces — ~70% fewer tokens with structure intact
  ([docs](https://repomix.com/guide/code-compress)).
- **Graph-native agent tooling**: GitNexus (10k+ stars, KuzuDB in `.gitnexus/`,
  served over MCP to Claude Code/Cursor —
  [repo](https://github.com/abhigyanpatwari/GitNexus)),
  [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext), and
  the Codebase-Memory paper ([arXiv 2603.27277](https://arxiv.org/html/2603.27277v1)),
  which benchmarked 31 repos: agents querying a structural graph over MCP used
  **10× fewer tokens and 2.1× fewer tool calls** than file-reading agents at
  ~90% of the answer quality. These tools index everything into a graph DB;
  graphlm's differentiator is the LLM-*curated* map (data flow, entry points,
  quick reference) — it should be queryable the same way.
- **Cursor** re-indexes incrementally via a Merkle tree of file hashes so only
  changed files are re-processed
  ([Cursor blog](https://cursor.com/blog/secure-codebase-indexing)).
- **Hierarchical repo summarisation** (ICSE LLM4Code 2025,
  [arXiv 2501.07857](https://arxiv.org/abs/2501.07857)) summarises units → files
  → packages with local LLMs; the file-level unit is the natural cache key.
- **OpenAI streaming usage**: `stream_options: {"include_usage": true}` returns
  real `prompt_tokens`/`completion_tokens` in a final chunk
  ([OpenAI cookbook](https://developers.openai.com/cookbook/examples/how_to_stream_completions)) —
  graphlm streams already but discards this.
- **GitHub renders Mermaid natively** in any Markdown file
  ([mermaid](https://github.com/mermaid-js/mermaid)); GitHub code scanning
  accepts **SARIF** from any tool via `codeql-action/upload-sarif`
  ([docs](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/integrate-with-existing-tools/upload-sarif-file)).
- **Architecture contracts as CI gates**: import-linter's layers/forbidden
  contracts ([docs](https://import-linter.readthedocs.io/en/latest/contract_types.html)).

## Proposals (ranked)

### 1. Serve the map to agents over MCP (`graphlm --serve`)
**Category:** feature / wow
**Impact 5 · Novelty 3 · Effort 3 · Fit 5**

**The idea.** graphlm's whole reason to exist is orienting a coding agent, yet
the agent must swallow a 30–60k-token Markdown file to ask one question. Expose
`GRAPH.json` through a stdio MCP server with a handful of typed, zero-LLM tools:
`overview`, `module(path)`, `neighbors(path, direction)` (LLM + AST edges,
labelled), `dependents(path, transitive)` for blast radius, `find(query)` over
quick-reference + symbols + summaries, `cycles()`, `entry_points()`, and
`staleness()` (stamped SHA vs current `HEAD`). Per the Codebase-Memory
benchmark this is the 10× token / 2× tool-call regime, and it makes the
existing `--install-skill` guide dramatically cheaper to follow.
**Inspired by.** GitNexus / Codebase-Memory (MCP-served code graphs); the
difference is graphlm serves its *curated* graph, not a raw symbol DB.
**Implementation sketch.**
- `graphlm/query.py` — pure functions over a loaded `CodebaseGraph` (no MCP
  dependency, fully unit-testable): adjacency built once from
  `import_edges ∪ deterministic_edges`, BFS for transitive dependents, a simple
  case-insensitive scorer for `find`.
- `graphlm/mcp_server.py` — thin `mcp` (FastMCP) wrapper; each tool is a
  ~5-line function that returns dicts/strings. Loads `<project>/.graphlm/GRAPH.json`
  via `diff.load_baseline` (already handles corrupt/old files) and re-reads it
  when the file mtime changes so a regen mid-session is picked up.
- `cli.py` — `--serve` flag short-circuits like `--install-skill` (single-command
  Typer app; a subcommand would break `graphlm <dir>`, per ADR-003).
- `pyproject.toml` — optional extra `mcp = ["mcp>=2,<3"]`; a clean install
  message if missing.
- `skills.py` guide gains a paragraph: "if `graphlm --serve` is registered as an
  MCP server, prefer its tools over reading `GRAPH.md`".
- Register: `claude mcp add graphlm -- graphlm --serve /path/to/repo`.
**Effort.** ~1 day. Main risk: MCP SDK API churn (v2.x) — keep all logic in
`query.py` so the wrapper is disposable.
**First step.** Write `query.py::neighbors()` + tests against the existing
fixtures.

### 2. Replace head-truncation with tree-sitter signature skeletons
**Category:** performance / feature
**Impact 5 · Novelty 3 · Effort 3 · Fit 5**

**The idea.** When a file exceeds `max_file_chars`, don't send its first 4000
characters — send a *skeleton*: module docstring, imports, every `class`/`def`
line with decorators and docstring first line, bodies replaced by `...`. A
1500-line module becomes ~150 lines the model can actually reason about
(all public symbols, the whole API), instead of the imports plus one class. Same
budget, far more signal per file — and it directly improves `file_summaries`,
`entry_points` and `quick_reference`, the sections agents use most.
**Inspired by.** Repomix `--compress` (~70% token cut, structure kept); aider's
TreeContext (only "lines of interest").
**Implementation sketch.**
- `graphlm/parsers/python.py` — `skeleton(code: bytes) -> str` walking
  `function_definition` / `class_definition` / `decorated_definition` nodes,
  emitting `def name(params) -> ret: ...` with the first docstring line;
  nested defs indented; everything else (`if __name__`, constants) kept if under
  N lines. Expose via a new `_Resolver.skeleton` (optional; `None` for packs
  without one).
- `scanner.py` — on `len(content) > max_file_chars` for a language with a
  skeleton, replace content with `skeleton()` + a header
  `# [skeleton: bodies elided, N lines]`; if the skeleton itself exceeds the cap,
  truncate the skeleton. Non-Python keeps head-truncation. Flag `--no-skeleton`.
- Redaction still runs on the skeleton (docstrings can hold secrets).
- Prompt: one sentence in `_build_instruction_block` explaining the marker.
**Effort.** ~1 day. Risk: fragment content is also what `cycles.compute_sloc_map`
counts — fix that at the same time by carrying the on-disk line count on
`FileFragment` (see the defect in "stands today").
**First step.** A `skeleton()` function + a fixture module with nested classes,
decorators, and async defs; assert the exact output.

### 3. Rank files with PageRank over AST def/ref tags; make pass 1 optional
**Category:** architecture / performance
**Impact 4 · Novelty 3 · Effort 4 · Fit 5**

**The idea.** Before pass 1 runs, graphlm already has an import graph. Add
def/ref tags (the `tags.scm` shipped in the Python wheel) and run PageRank over
files, weighting references to a file's definitions aider-style. Use the ranking
to (a) order files within `max_pass2_files` so the budget trims the least
central files first (today: alphabetical — `filter_requested_files` sorts by
path), (b) make `--dry-run` select what a real run would, and (c) offer
`--pass1 rank` to skip the paid pass-1 call entirely — deterministic, instant,
and reproducible across models.
**Inspired by.** Aider `repomap.py` (PageRank on file graph; `_private` ×0.1,
many-definers ×0.1, sqrt of ref count).
**Implementation sketch.**
- `graphlm/rank.py` — stdlib PageRank (power iteration, ~30 lines; no networkx),
  `rank_files(edges, tags) -> dict[str, float]`, plus the config-file boost
  `_rank_file` already encodes so `pyproject.toml`/`README.md` stay on top.
- `parsers/python.py` — `tags(code) -> list[Tag(kind, name, role)]` from the
  wheel's `tags.scm` via the existing `_backend.build_query`.
- `__init__.py` — `pass1_mode: Literal["llm","rank","both"]`; `"both"` (default)
  = LLM list, ordered by rank; `"rank"` = top-N by rank, no call.
**Effort.** ~1 day. Risk: PageRank on a sparse import graph is flat; the def/ref
edges are what make it informative — validate on the `argus` repo (135 modules).
**First step.** Extract tags for one fixture and print the ranking.

### 4. Incremental regeneration keyed on file content hashes
**Category:** performance / architecture (flagship)
**Impact 5 · Novelty 4 · Effort 2 · Fit 4**

**The idea.** Stamp every `file_summaries[]` entry with a BLAKE2 hash of the
file bytes it was produced from. On the next run, files whose hash is unchanged
are **not re-sent**; their prior summary + symbols are injected as a compact
"known context" block, and only changed/new files go in full. Global sections
(`modules`, `data_flow`, `architecture_notes`, `quick_reference`) are still
regenerated — with far more room, because the unchanged files now cost ~400
chars each instead of 4000. A one-file change on a large repo drops from ~200s
to tens of seconds and from ~100k to ~20k input tokens.
**Inspired by.** Cursor's Merkle-tree incremental indexing; ICSE 2025
hierarchical summarisation (file-level units as the cache boundary).
**Implementation sketch.**
- `models.py` — `FileSummary.content_hash: str | None`; bump
  `GRAPH_META_SCHEMA_VERSION` is *not* needed (additive, optional), but note it
  in ADR-001's contract.
- `scanner.py` — `FileFragment.content_hash` computed from the untruncated bytes.
- `context.py` — `assemble_pass2_prompt(..., prior: dict[path, FileSummary])`
  emits a `## Previously analysed (unchanged) files` block; prompt instructs the
  model to copy those summaries through unchanged.
- `__init__.py` — load the prior `GRAPH.json` (reuse `diff.load_baseline`), build
  the unchanged set, and — belt and braces — **splice the prior summaries back
  in locally** after pass 2 so a lazy model can't drop them.
- `--full` flag to force a cold run; `GRAPH_DIFF` becomes genuinely small.
**Effort.** 2–3 days. Risks: global-section coherence with partial context
(mitigate: `--full` every N runs or when >40% of files changed); interaction
with ADR-002 identity keys (unchanged — summaries keep their `path`).
**First step.** Add `content_hash` end-to-end and assert it round-trips through
`GRAPH.json`; no behaviour change yet.

### 5. AST symbol table as ground truth for `file_summaries.symbols`
**Category:** feature / correctness
**Impact 4 · Novelty 3 · Effort 4 · Fit 5**

**The idea.** The parser already extracts classes and functions and throws them
away. Feed a per-file definitions table into pass 2 (like the edge table, with
the same budget cap and "not exhaustive" framing), then post-validate: LLM
symbols not in the AST set for a Python file are marked `verified: false` (or
dropped with `--strict-symbols`). Agents get a symbol list they can trust.
**Inspired by.** Original — derived from the unused `ParsedFile.functions /
exports` in `parsers/python.py`; same "AST is ground truth, not a replacement"
principle as #19.
**Implementation sketch.** `context._build_symbol_block()` mirroring
`_build_edge_block`; `Symbol.verified: bool | None`; a `verify_symbols()` pass in
`generate_graph`; render a ✓ column in `GRAPH.md`.
**Effort.** ~1 day. Shares the tags infrastructure with #3.
**First step.** Render the symbol block for a fixture and eyeball the token
cost.

### 6. Run telemetry in `meta`: real token usage + LLM-vs-AST faithfulness score
**Category:** ops / DX (quick win)
**Impact 3 · Novelty 5 · Effort 5 · Fit 5**

**The idea.** Two free measurements per run, stamped into `meta` and printed:
(a) send `stream_options.include_usage` and record actual
`prompt_tokens`/`completion_tokens` for each pass, plus the measured
bytes-per-token vs graphlm's estimate — the calibration #17 did by hand becomes
automatic and per-endpoint; (b) score the LLM's `import_edges` against the AST
`deterministic_edges` (precision / recall on the Python subset) — the first
quantitative quality signal for "does model X produce a faithful map?", free
because the labels already exist. Also fix `--dry-run` to report the AST edge
count.
**Inspired by.** OpenAI streaming usage chunk; original for the faithfulness
metric (derived from the do-not-contradict table).
**Implementation sketch.** `llm.py` — parse the final `usage` chunk, return it
alongside content; `models.py` — `GraphMeta.usage` (optional, additive) and
`GraphMeta.faithfulness`; `graphlm/faithfulness.py` — pure set arithmetic;
`render.py` — one line under the directive; `cli.py` — print both.
**Effort.** Half a day. Risk: endpoints that ignore `stream_options` → `usage`
stays `null` (explicitly allowed).
**First step.** Add `stream_options` to the payload and assert the mock's usage
chunk is captured.

### 7. Put the ground truth in the pictures: Mermaid in `GRAPH.md`, AST edges + cycles in `GRAPH.html`
**Category:** DX / wow (quick win)
**Impact 3 · Novelty 2 · Effort 5 · Fit 5**

**The idea.** Render a directory-level Mermaid `flowchart` of the deterministic
edges at the top of `GRAPH.md` — GitHub, GitLab and most Markdown previews draw
it natively, so the map has a diagram that works offline and in a PR (the D3
page needs a CDN). Cycle edges are styled red. In the HTML, add the AST edges as
a distinct layer (solid, labelled "parser"), highlight cycle members, and add
layer toggles — today the page silently shows only the LLM's guesses.
**Inspired by.** GitHub native Mermaid; the gap found in `html_render._build_links`.
**Implementation sketch.** `render.py::_render_mermaid(edges, cycles, max_nodes=40)`
collapsing files to their top-level package/dir, `classDef cycle stroke:#e11`;
`html_render._build_links` adds `type: "ast"` links and `in_cycle` on nodes;
template gets three checkboxes.
**Effort.** Half a day. Risk: Mermaid node cap on huge repos — collapse to
directories and cap at 40 nodes with an "N more" note.
**First step.** Emit the Mermaid block for the `cyclic_project` fixture.

### 8. Architecture contracts + SARIF: `graphlm check`
**Category:** ops / security
**Impact 3 · Novelty 3 · Effort 3 · Fit 3**

**The idea.** A `.graphlm/contracts.toml` with import-linter-style `layers` and
`forbidden` rules evaluated against the deterministic edges (no LLM), plus
`--sarif` output for cycles and violations so they appear as GitHub code-scanning
annotations on the PR. Cross-language once packs land — one contract file for a
polyglot repo.
**Inspired by.** import-linter contracts; GitHub SARIF upload.
**Implementation sketch.** `graphlm/contracts.py` (parse TOML via stdlib
`tomllib`, evaluate against edges), `--check` flag returning exit 3 on
violation, `sarif.py` writing `GRAPH.sarif` (rule ids `graphlm/cycle`,
`graphlm/forbidden-import`).
**Effort.** ~1.5 days. Risk: overlap with import-linter for pure-Python repos —
the value is the polyglot + agent-readable angle, so ship after the JS/TS pack.
**First step.** Evaluate one `forbidden` rule against `cyclic_project`.

## Killed ideas (and why)

- **Vendor D3 inline for offline HTML** — +280 KB per map; Mermaid (#7) gives an
  offline diagram for free.
- **Embedding index for semantic "where is X"** — new heavy dependency and a
  second model; `quick_reference` + MCP `find` (#1) covers the agent use case
  locally.
- **Watch mode / git hook auto-regeneration** — explicitly rejected in ADR-001
  (the agent is the scheduler); #4 makes regen cheap instead.
- **Hierarchical map-reduce for monorepos** — real, but #4 and #2 must land
  first; it is a 1-week build with prompt-coherence risk. Revisit after #4.
- **Cross-language edges / plugin API** — locked out of scope by the #42 owner
  decisions.
- **JS/TS resolver** — already planned and scoped (`docs/plans/PHASE1-HANDOFF.md`);
  not an innovation proposal.
- **Port the LLM client to async** — one sequential request per pass; nothing
  to parallelise until #4's per-file passes exist.

## Suggested order of attack

Ship the two quick wins (#6, #7) and #1 first: they touch disjoint files, need no
prompt changes, and #1 immediately changes what agents do with the map. Then
#2 (skeletons) — it raises the quality of every section and fixes the cycle-score
defect on the way. #3 and #5 share the tags query and should be one branch pair.
#4 is the flagship but depends on nothing above except the hash field; start it
once #2 has settled what a "file's content" means, and land #8 after the JS/TS
pack so contracts are polyglot from day one.

---

# Jev-focused addendum — deepening the TypeSafe integration
*Generated 2026-09-21 · based on commit `1de4d39` (feat/module-importance) · scope: "Jev uses and enhancements for the greatest impact"*

## Where the Jev integration stands today (verified this session)

graphlm now uses TypeSafe/Jev in three places, all at **graph-generation** time, all
best-effort and gated (key + `graphlm[typesafe]` extra), never blocking the graph:

- **`evidence.score`** — a SOFT Noul per `file_summary`: is the prose backed by the
  source the model saw? → `meta.evidence_support`. Shipped (#167).
- **`evidence.score_importance`** — a Score per module over a leaf→orchestrator role
  ladder, fused with structural degree → `ModuleDescription.role`/`degree`, rendered
  as the `## Modules` Importance column. On `feat/module-importance` (unmerged).
- **`faithfulness.score`** — pure set intersection, not Jev (LLM edges vs AST edges).

A pre-registered evaluation this session (4 repos, hand-labeled by degree-blind
sub-agents) showed importance **beats raw import degree** at finding load-bearing
files (mean τ-b gap +0.27 on file-granular repos; on `softreq`, degree was
*negatively* correlated with truth), and is stable across LLM drafts (≤0.10 role
swing). Evidence support flags only 2.3% of summaries with one glue-file false
positive. So the *judgment* primitives work; the open question is **where else Jev
earns its call.**

### The gaps that motivate the proposals below
1. **`--serve`'s `find` is a substring/path matcher** (`query.resolve_path`), on the
   agent hot path — the one place a Jev call would happen at *query* time, not
   generation time.
2. **Six of nine substantive `CodebaseGraph` fields have no oracle** — only
   `import_edges`, `file_summaries`, and `modules` are Jev-checked. `data_flow`,
   `architecture_notes`, `entry_points`, `quick_reference`, `test_organization`,
   `database_schema` are unverified LLM prose.
3. **Jev confidence is discarded.** Every Choice/Score returns a `.confidence`;
   graphlm reads none of it. A low-confidence role score is displayed as fact.
4. **The diff can't detect renames** (ADR-002 decision 2 locks it as remove+add).

## What the best in this space are doing (TypeSafe patterns graphlm hasn't used)

From the TypeSafe docs (patterns.md, use-case-map.md, cookbooks):
- **Confidence-gated routing** — use `.confidence` as a second decision axis to
  withhold or escalate uncertain judgments. graphlm uses none of it.
- **Verification** (citation-check cookbook) — a Noul per claim against its evidence;
  graphlm applies this to summaries only, not to notes/flows/entry-points.
- **Entity matching** (entity_alignment cookbook) — a 3-level Score
  (different / maybe-same / same) with companion Nouls, *threshold-free*, settling
  89% of pairs automatically. Directly applicable to rename detection in the diff.
- **Semantic search** (semantic_find, rerank cookbooks) — a Noul with fixed criteria
  scores candidates against a natural-language query more *consistently* than a
  general LLM. NB: the rerank cookbook's 5%→18% top-1 lift is a *retrieval* result and
  does **not** transfer to importance ranking (all modules are in scope, not a
  candidate shortlist) — cited only for the query-time search shape.

## Proposals (ranked)

### 1. Semantic `find` for `graphlm --serve` — a Jev call at query time
**Category:** feature | wow
**Impact 5 · Novelty 5 · Effort 3 · Fit 5**

**The idea.** `--serve` exposes the map to a coding agent over MCP, but `find` is a
deterministic path/substring match (`query.resolve_path`). Add a **semantic** find:
the agent asks "which module handles rate-limiting?" and a Jev Noul scores each
module's `description`+`summary` against that natural-language query, returning the
best matches with probabilities. This is the *only* Jev use at **query** time rather
than generation time — a genuinely different integration shape from everything built
so far — and "which file does X" is the question agents actually ask a codebase map.
**Inspired by.** TypeSafe `semantic_find` + `rerank` cookbooks (Noul-per-candidate
against a query). Original application to an MCP code-map server.
**Implementation sketch.** New `query.semantic_find(index, query, *, api_key, client)`
in `query.py` (the pure-function layer, already SDK-free and testable). It batches a
Noul per module — instructions carry the query + the module's description/summary,
criteria "this module is where you'd go to do/understand <query>". Returns ranked
`(path, probability)`. Expose as a **new MCP tool `search`** (NOT a silent change to
`find` — `--serve` is documented as eight *zero-LLM* tools; `search` is the opt-in
LLM one, gated on the key + extra, falling back to a clear "needs graphlm[typesafe]
+ key" ToolError). `mcp_server.py` wraps it like the others.
**Effort.** ~1 day. Risk: latency on a hot path — mitigate by batching (~15/req, the
proven size) and caching per (query, map-mtime). A miss falls back to the existing
`find`.
**First step.** Write `query.semantic_find` + a no-network unit test with an injected
fake client (the `test_evidence.py` pattern), before touching `mcp_server.py`.

### 2. Verify the six unverified prose fields (`data_flow`, `architecture_notes`, …)
**Category:** feature | ops
**Impact 4 · Novelty 2 · Effort 2 · Fit 5**

**The idea.** `evidence.score` verifies `file_summaries` only. Extend the exact same
Noul-against-evidence shape to the graph's other LLM-authored claims — most valuably
`data_flow` (the least trustworthy structural field: pure LLM inference, no AST
backing) and `architecture_notes` (the highest-level claims, entirely unchecked).
Each gets a support probability into `meta`, and low-confidence ones surface in the
telemetry line and (optionally) get dropped. Completes the verification story this
session started.
**Inspired by.** TypeSafe citation-check cookbook. Directly generalizes the shipped
`evidence.score`.
**Implementation sketch.** Generalize `evidence.score` into a `verify_claims(claims,
evidence_by_path, *, kind, api_key, client)` that takes a claim + its evidence set and
the SOFT criteria per claim kind. For `data_flow` (source→dest+description) the
evidence is the source+dest files' `frag.content`; for `architecture_notes` the
evidence is the whole scanned tree + edges (a note is a global claim). New
`meta.claim_verification: {data_flow: …, notes: …}`. Same never-raise/gate discipline.
**Effort.** ~1 day. Risk: `architecture_notes` are *global* claims with no single
evidence file — may need the edge table + tree as evidence, which is larger context;
measure token cost per note.
**First step.** `verify_claims` for `data_flow` only (well-scoped evidence), scored on
the 4 experiment repos to check the flag rate before extending to notes.

### 3. Confidence-gated display of Jev judgments
**Category:** DX | reliability
**Impact 3 · Novelty 3 · Effort 1 · Fit 5**

**The idea.** Every Jev Score/Choice returns `.confidence`; graphlm discards it. A
role score of 2.4 at confidence 0.5 is a guess shown as fact. Capture confidence
alongside `role`, and in the renderer *withhold or mark* low-confidence importance
(show "—" or a "·" marker instead of a number below a confidence floor) rather than
presenting an uncertain rank as authoritative. Directly addresses the "modest
absolute τ / marginal at directory granularity" weakness the evaluation found —
don't assert what Jev isn't sure of.
**Inspired by.** TypeSafe confidence-gated-routing pattern.
**Implementation sketch.** `score_importance` already calls `system_one`; capture
`resp.scores[k].confidence` beside `.score`, thread an optional
`ModuleDescription.role_confidence`. In `render._fused_importance`, gate: below
`_CONFIDENCE_FLOOR` the module renders with a muted/marked importance, not a hard
number. Additive-optional field; byte-identical fallback preserved.
**Effort.** ~half a day. Risk: none material — it's read-only additive signal.
**First step.** Add `role_confidence` capture in `_run_scores`, print the confidence
distribution across the 4 experiment repos to pick a defensible floor before gating.

### 4. Rename-aware diff via entity-alignment Score — supersede ADR-002 decision 2
**Category:** feature | architecture
**Impact 4 · Novelty 4 · Effort 3 · Fit 4**

**The idea.** ADR-002 decision 2 **locks** the graph-vs-graph diff as added/removed
only with structural identity keys — "renames are remove+add (no rename heuristics —
locked)." That lock predates Jev. A rename today shows as one deletion + one addition,
noise on every refactor. A TypeSafe **entity-alignment Score** ("do these two module
descriptions describe the same component? different / maybe / same") can match an
added module to a removed one across a path change, threshold-free — turning churn
into a clean "renamed A → B". **This proposal explicitly asks to supersede ADR-002
decision 2 for renames**, and argues the supersession: the ADR rejected rename
heuristics because *string* heuristics are unreliable and would create false diff
identity; a calibrated semantic Score is a different instrument, gated and best-effort,
that can be wrong without corrupting the structural keys (it annotates, it doesn't
change the identity contract).
**Inspired by.** TypeSafe `entity_alignment` cookbook (3-level Score + companion
Nouls, 89% auto-settled). Supersedes ADR-002 decision 2.
**Implementation sketch.** In `diff.py`, after computing added/removed module sets,
run a Jev Score over the cartesian product of (removed × added) *only when both sets
are non-empty and small* — instructions carry both descriptions, levels
different/maybe/same. A "same" pair (rounded) becomes a `renamed` entry in
`GraphDiff`; "maybe" is reported but not auto-applied. Gated + never-raise; when Jev
is off the diff is byte-identical to today (the ADR behavior is the fallback). New
ADR-016 recording the supersession.
**Effort.** ~1.5 days incl. the ADR + guarding the cartesian blow-up (cap the pair
count; skip when either set is large). Risk: pairing cost is O(removed×added) — cap it.
**First step.** Write ADR-016 (the supersession argument) and get Greg's sign-off
BEFORE code — this changes a locked decision.

### 5. Confidence-driven escalation stamp (the "know when Jev didn't help" signal)
**Category:** ops
**Impact 2 · Novelty 3 · Effort 2 · Fit 4**

**The idea.** The evaluation showed Jev degrades to "no worse than degree" on a
non-app domain (slate, a compiler). graphlm can *detect* that itself: when the
importance Score's confidence is low across most modules AND role barely diverges
from degree, stamp `meta` with a "low semantic signal — importance is degree-like on
this repo" note, so a reading agent knows not to over-trust the ranking. Turns the
honest limitation into a self-aware feature.
**Inspired by.** Original — derived from the slate probe result this session.
**Effort.** ~half a day. Risk: defining "low signal" without overfitting to slate.
**First step.** Compute mean role-confidence + role/degree correlation per repo across
the 4 experiment graphs; see if slate is separable from the apps by a simple rule.

## Killed ideas (and why)
- **Reframe importance as pairwise reranking.** The rerank cookbook's 5%→18% lift is
  a *retrieval* result (shortlist of candidates, relevance unknown); importance ranks
  a fixed in-scope module set — a different task, the number won't transfer. Absolute
  Noul/Score is already right.
- **Hierarchical classification of the module tree.** The argus granularity mismatch
  is a *join* problem (file labels vs directory modules), not something a hierarchical
  judgment fixes; no evidence flat scoring is the limiter.
- **Jev-generated architecture notes.** Jev doesn't generate; and the refine-loop
  spike this session proved feeding judgments back to the generative model is
  net-neutral-to-negative. Verify notes (proposal #2), don't generate them.
- **Replace `faithfulness` with a Jev call.** It's an exact set intersection with a
  perfect oracle (AST edges); a probabilistic judgment would be strictly worse.

## Suggested order of attack
Build **#1 (semantic `find`)** first — it's the flagship, hits the agent hot path, and
is the one genuinely new integration shape (query-time Jev). It shares nothing with the
generation path, so it can land independently. Then **#3 (confidence gating)** as a
half-day quick win that hardens the *shipped* importance feature against its own
measured weakness. **#2 (verify prose fields)** is the highest-certainty value and the
honest completion of the evidence story — do it once #1 proves the query-time pattern.
**#4 (rename diff)** is gated on Greg approving the ADR-002 supersession — ADR first,
code second. All of these assume `feat/module-importance` has merged (the Jev surface
lives there); branch prototypes from it, not `develop`, until it does.
