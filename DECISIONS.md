# Architecture Decision Records

Significant, hard-to-reverse decisions for graphLM. Newest first.

---

## ADR-001 — Self-refreshing graph: provenance stamp + agent-scheduled refresh

**Date:** 2026-08-30
**Status:** Accepted (Release one implemented; `GRAPH_DIFF.*` is a fast-follow)
**Context / plan:** `docs/plans/self-refreshing-graph.md`

### Context

A generated graph goes stale the moment the code moves on, but nothing tells a
reader (human or coding agent) that it has. We want the output to be
*self-refreshing without any hook or flag*: it should carry its own provenance
and a directive that prompts regeneration when the code has changed.

### Decision

1. **The agent is the scheduler, not graphlm.** The generated `GRAPH.md` carries
   a top-of-file *refresh directive*; a coding agent reading the file decides
   whether to regenerate. graphlm stays dumb — when invoked it always
   regenerates and re-stamps; it never declines, and holds no staleness logic.
   Rejected alternatives: a git hook (taxes every session with a ~200s paid LLM
   run) and a `--if-stale` flag (puts scheduling in the wrong place).

2. **Staleness = git SHA mismatch.** The stamp records the git `HEAD` the graph
   was generated against; `HEAD != stamped_sha` is the trigger. `created_at` is
   human context only, never the trigger.

3. **The stamp is authoritative in `GRAPH.json`; the `GRAPH.md` directive is
   rendered from it.** One source of truth, so the two cannot drift.

4. **The directive is advisory.** The agent may ignore it. Best-effort staleness
   is the correct trade — better than forcing a regen — and the docs say so.

5. **Non-git repos degrade, they don't error.** No SHA → `commit_sha = null`
   (preserved explicitly in JSON, so "no git tracking" is distinguishable from
   "old format, field absent") and the directive falls back to the agent's
   judgment. Git capture is failure-tolerant: not a repo, git absent, or an
   empty repo all yield `null`, never an exception.

6. **Wording: "generated against commit X", never "reflects X".** The graph is
   built from files on disk, which may include uncommitted changes, so a graph
   can be SHA-fresh yet not match the working tree. We stamp `HEAD` and do not
   chase the dirty-working-tree case (over-engineering for release one); the
   honest phrasing avoids overclaiming.

7. **The metadata block is versioned (`schema_version`), making the output
   format an *input* contract.** This is the load-bearing, ADR-worthy decision.
   The fast-follow `GRAPH_DIFF.*` feature reads graphlm's *own* prior
   `GRAPH.json` to diff two graphs; for that read to be safe across future
   format changes, the persisted meta is versioned so a format change is
   *detected*, not silently misparsed. Coupling output shape into an input
   contract is a deliberate, named cost, accepted for the diff capability.

8. **Meta is filled locally, never emitted by the LLM.** Like `directory_tree`
   and `deterministic_edges`, `generate_graph` sets `graph.meta` after pass 2
   (and in `--dry-run`), overwriting anything the model may have hallucinated
   into a `meta` field. It is not in the pass-2 instruction block, so it costs
   no output tokens and cannot be spoofed by scanned file content.

### Consequences

- `graphlm/provenance.py` is the first and only module that reads git / shells
  out. Kept isolated and failure-tolerant.
- A git SHA is accepted only when `git rev-parse HEAD` exits 0 **and** stdout is
  a 40- or 64-hex hash — this rejects the empty-repo case, where git prints the
  literal `HEAD` with a non-zero exit.
- **Known limitation (`-o`):** when output is written somewhere other than the
  scanned repo (`-o <elsewhere>`), an agent that reads that `GRAPH.md` and runs
  `git rev-parse HEAD` in *its own* directory compares against the wrong repo.
  Documented, not engineered around, for release one.
- **Known behavior (subdirectory):** pointing graphlm at a subdirectory of a
  repo stamps the *containing* repo's `HEAD` — git's own behavior, and the
  correct staleness anchor for that subtree.
- `--dry-run` fills the stamp on the graph object but the CLI still prints stats
  and does not write files (unchanged contract); the stamp is exercised on any
  real run and via the library `write()` path.

### Fast-follow (separate ADR before building)

`GRAPH_DIFF.*` — a graph-vs-graph diff (not a code diff): read the prior
`GRAPH.json` via the versioned model before overwriting, then report
modules/edges/cycles/data-flows/entry-points added and removed. Identity keys
per dimension *are* the diff's contract and must be chosen deliberately. Renames
are remove + add for the first cut. Its artifact shape is its own design choice.
