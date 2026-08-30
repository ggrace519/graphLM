# Plan: Self-refreshing graph (provenance stamp + agent directive + GRAPH_DIFF)

**Status:** Approved design, not yet built. Written for a fresh agent-loop to
implement cold.
**Owner decision baseline:** discussion in session 2026-08-30, all points below
are Greg's decisions, not open questions.
**Repo state at write time:** `main` @ `54d17f5`.

---

## Goal

Make the generated graph *self-refreshing without any hook or flag*: the output
document carries its own provenance (when + which commit it was built against)
and a plain-language directive telling a coding agent to regenerate it when the
code has moved on. The **coding agent is the scheduler** — it reads the
directive, checks staleness itself, and decides whether to re-run `graphlm`.
graphlm stays dumb: when invoked it always regenerates and re-stamps.

This is deliberately *not* a git hook and *not* a `--if-stale` flag. Those were
considered and rejected: a hook taxes every session with a ~200s paid LLM run,
and a staleness flag puts scheduling logic in the wrong place. The agent already
reads `GRAPH.md` (nudged by the rules/memory layer); the directive rides along
in that existing loop with zero integration surface.

## Decisions (locked — do not relitigate)

- **Staleness = git SHA mismatch.** `HEAD != stamped_sha` is the trigger.
  `created_at` is human context only, never the staleness trigger.
- **The stamp lives authoritatively in `GRAPH.json`** (structured, already the
  source of truth for output shape). The `GRAPH.md` top-of-file directive is
  *rendered from* that stamp — the two must not be allowed to drift.
- **The directive is advisory.** The agent may ignore it. Staleness is
  best-effort, not guaranteed. This is the correct trade (better than a forced
  regen); be honest about it in docs.
- **`graphlm`, when invoked, always regenerates** — it never declines or
  second-guesses. No staleness logic inside graphlm. The *agent* decides whether
  to invoke; only two things prompt a run: (1) code changed (SHA moved), or (2)
  the agent judges it warranted (e.g. it just made sweeping edits).
- **Non-git repo → always regenerate**, and the stamp/directive degrade: no SHA,
  so the directive falls back to "regenerate when you believe the code changed"
  and staleness rests on the agent's judgment alone.
- **`GRAPH_DIFF.*` is a graph-vs-graph diff** (old `GRAPH.json` vs. new), NOT a
  code diff — git already does code diffs better. It reports what changed in the
  *graph*: modules/edges/cycles/data-flows/entry-points added and removed.
- **Renames are remove + add for the first cut.** No rename-matching heuristics.
- **The metadata block is versioned** so graphlm can read its own prior output
  across future format changes without the diff silently breaking. Output format
  becoming an *input* contract is a deliberate, named coupling.
- **Word choice: "generated against commit X", not "reflects commit X".** The
  graph is built from files on disk, which may include uncommitted changes, so a
  graph can be SHA-fresh yet not match the working tree. We stamp `HEAD` and do
  NOT chase the dirty-working-tree case (over-engineering for release one) — the
  honest wording just avoids overclaiming.

## Scope split

### Release one — Stamp + directive (small, no hard dependencies)

Delivers the whole "self-refreshing doc" idea. Needs no diff.

### Fast-follow (its own issue/ADR) — `GRAPH_DIFF.*`

Separable: only has value once two stamped graphs exist, and even remove+add
graph comparison (choosing the diff artifact's own shape, matching entities
across runs by identity key) is real work that must not gate the stamp shipping.

---

## Release one — implementation notes

**Grounded against the current code (verify these still hold before editing):**

- `CodebaseGraph` (`graphlm/models.py`, ends ~line 165) is the Pydantic schema and
  single source of truth for output shape. Add the metadata here.
- `write_outputs()` (`graphlm/render.py:153`) writes `GRAPH.md/json/html` via
  `*_suffix` params defaulting to `"GRAPH"`. The stamp is serialized into JSON
  here and the directive rendered into the top of the Markdown here.
- The CLI resolves the output dir with `output_destination()` and writes via
  `result.write(dest, ...)` (`graphlm/cli.py:193-194`). The library itself only
  writes when `output_dir` is set; the CLI owns the write. Keep that split (it
  was fixed in #8 — do not "simplify" it).
- **Nothing in `graphlm/` reads git today** (only `.git` appears as a scan
  exclude). This feature introduces the first git read — keep it isolated and
  failure-tolerant (see below).

**1. Metadata model.** Add a small versioned metadata object to `CodebaseGraph`
(e.g. a `GraphMeta` submodel: `schema_version: int`, `created_at: str` (ISO
8601, UTC), `commit_sha: str | None`, `graphlm_version: str | None`). Default it
so existing callers/tests that construct `CodebaseGraph` without meta still work.
Because the pass-2 prompt hand-writes the JSON schema for the LLM, **the model is
NOT emitted by the LLM** — meta is filled *locally* by graphlm after pass 2
(exactly like `directory_tree` and `deterministic_edges` are filled in
`generate_graph`), never requested from the model. Do not add it to the
instruction block.

**2. Capture the commit SHA.** In `generate_graph` (or a helper it calls),
resolve `git rev-parse HEAD` for the scanned project dir. Use `subprocess` with
argv list (no shell), cwd = project dir. **Failure-tolerant:** not a git repo,
git not installed, detached/empty repo → `commit_sha = None`, never raise. This
is the non-git path; it must be silent and normal, not an error.

**3. Fill meta locally.** After pass 2 (and in the `--dry-run` path too, so
stamps are consistent), set `graph.meta = GraphMeta(created_at=now_utc_iso(),
commit_sha=<sha or None>, schema_version=CURRENT, graphlm_version=<pkg version>)`.

**4. Serialize into JSON** via the normal model dump in `write_outputs`.

**5. Render the directive into `GRAPH.md`.** A top-of-file block, generated from
meta, in two forms:
   - *Git form* (sha present): a short human/agent-readable block naming the
     commit and date, instructing: "This map was generated against commit
     `<sha8>` on `<date>`. Before relying on it, check whether the repo has moved
     on — compare `git rev-parse HEAD` to that commit; if they differ, regenerate
     with `graphlm <path>`."
   - *Non-git form* (sha None): "Generated `<date>`; no commit tracking available
     — regenerate with `graphlm <path>` when you believe the code has changed."
   Keep the exact wording tight and unambiguous; it is read by a model. Use
   "generated against", never "reflects" (dirty-tree honesty).

**6. Docs / adoption.** Add a short "self-refreshing graph" section to README and
`CLAUDE.md`: what the stamp means, that the directive is advisory, and one
copy-paste line for an `AGENTS.md` / rules file ("a codebase map lives at
`GRAPH.md` — read it before exploring, and follow its refresh directive"). Bump
any "as of" header. Update `CLAUDE.md`'s Output section to describe the meta
block and the two directive forms.

**7. Tests (≥90%, concurrent with impl).**
   - meta populated with a fake/real SHA in a git fixture; `commit_sha is None`
     in a non-git tmp dir; neither path raises.
   - `GRAPH.md` contains the git-form directive when sha present, the non-git
     form when absent.
   - `GRAPH.json` round-trips through `CodebaseGraph.model_validate_json` with
     meta present; and an *old* JSON with **no** meta block still validates
     (backward-read — this is the versioned-contract guarantee).
   - directive wording says "generated against" (guards the dirty-tree honesty).

**Fix in passing (unrelated drift, same theme):** `graphlm/cli.py` `--max-output-tokens`
help still says "else 32000" — the default is 128000 since #26. Correct it.

## Fast-follow — `GRAPH_DIFF.*` implementation notes

- **Baseline:** read the *existing* `GRAPH.json` in the output dir (if any)
  BEFORE overwriting it, parse via the versioned model (this is why the metadata
  block is versioned and why graphlm reads its own output). Keep the parsed old
  graph in memory; write the new graph; then compute and write the diff.
- **First run / no prior GRAPH.json:** still WRITE `GRAPH_DIFF.*`, as an explicit
  "initial graph — no prior version to compare" — never skip or leave empty, or
  an agent can't tell "no changes" from "never compared."
- **Diff dimensions** (each as added/removed lists; remove+add for renames):
  `modules` (key by `path`), `import_edges` + `deterministic_edges` (key by
  `(from_path, to_path, kind)`), `import_cycles` (key by node set), `data_flow`
  (key by `(source, destination)`), `entry_points` (key by `(path, name)`),
  `file_summaries` (key by `path`). Pick identity keys deliberately and document
  them; that choice *is* the diff's contract.
- **Old→new SHA range** goes in the diff header (from old meta.commit_sha to new
  meta.commit_sha) so a reader knows exactly which commit span it covers.
- **Artifact shape** (`GRAPH_DIFF.md` + `.json`; html optional) is its own design
  choice — decide it in the fast-follow ADR, not here.
- Its own issue + DECISIONS.md ADR before building.

**Scoped (2026-08-30):** tracking issue **#28**; design decisions settled in
`DECISIONS.md` **ADR-002** (where the diff runs, added/removed-only, the three
baseline states, `deterministic_edges` None-vs-empty, artifact shape,
on-by-default). **Implemented (2026-08-30)** — `graphlm/diff.py`, wired into
`write_outputs`, `--no-diff` flag; tests in `tests/test_diff.py`.

## Non-goals / explicit traps to avoid

- No git hook. No `--if-stale` / `--skip-if-fresh` flag. No mtime-based staleness.
- graphlm never declines to run when invoked.
- No rename-matching in the first diff cut.
- Do not chase the dirty-working-tree case; stamp HEAD, word it honestly.
- Do not add meta to the LLM instruction block or request it from the model —
  fill it locally, like `directory_tree`/`deterministic_edges`.
