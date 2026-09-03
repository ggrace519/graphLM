# Innovation #2 — signature skeletons for oversized files

Branch: `innovation/skeletons` (from `main` @ `692d819`).

## The problem

`scan_project` caps each file at `max_file_chars` (default 4000). A file over
the cap was sent as its **first 4000 characters** — for a 1500-line module that
is the imports and the first class. Everything below the cut was invisible, so
the LLM's `file_summaries`, `symbols`, `entry_points` and `quick_reference`
for big files were guesses. Separately, `cycles.compute_sloc_map` counted the
lines of that *truncated* fragment, so every large file in an import cycle was
under-weighted in the `log10(total_lines) * cycle_length` risk score.

## What this branch does

1. **`parsers.python.skeleton(code) -> str`** renders a module as its API
   surface with Tree-sitter: module docstring head, imports verbatim (including
   under a top-level `try:` / `if TYPE_CHECKING:`), every class/def header with
   decorators and multi-line signatures intact, each docstring's first line,
   class attributes and constants that fit in two lines (longer ones become
   `NAME = {…}  # N lines elided`), `if __name__ == "__main__":` reduced to its
   header. Bodies are `...`. First line:
   `# [graphlm skeleton: bodies elided; N source lines]`.
2. **`parsers.base.skeleton_for(path, code) -> str | None`** dispatches by
   language through the resolver registry (`_Resolver.skeleton`, optional).
   It never raises — no language / no renderer / grammar missing / renderer
   bug all return `None`, which means "keep head-truncation".
3. **The scanner uses it**: a file over the cap is replaced by its skeleton;
   only if the skeleton is *still* over the cap (or there is none) does the
   head slice apply. Secret redaction runs *after* skeletonisation.
4. **Real line counts**: `FileFragment.line_count` is captured before any cut
   and `compute_sloc_map` uses it, so cycle scores weigh big files correctly.
5. **Prompt**: `_build_instruction_block` explains the marker — signatures are
   exact, do not invent behaviour for elided bodies.
6. **`--no-skeleton`** / `scan_project(skeleton=False)` /
   `generate_graph(skeleton=False)` restore the old head-truncation.

## Try it

```bash
uv sync --group dev
uv run pytest -q                      # 489 passed (404 on main + 85 new)
uv run mypy graphlm --ignore-missing-imports

# Token effect on graphLM's own tree — same tree, same 80 pass-2 files:
uv run graphlm . --dry-run --no-skeleton   # head-truncation: Pass 2 ~73004 tokens
uv run graphlm . --dry-run                 # skeletons:       Pass 2 ~64050 tokens (-12%)
# (main @ 692d819, a smaller tree without this branch's new files: ~67259)

# Eyeball a skeleton:
uv run python -c "
from pathlib import Path
from graphlm.parser import skeleton_for
p = Path('graphlm/scanner.py'); print(skeleton_for(p, p.read_bytes()))"
```

`graphlm/scanner.py` (23050 chars) skeletonises to 2432 chars and still lists
`FileFragment`, `ScanResult`, `estimate_tokens`, `_should_exclude`,
`_is_binary`, `_is_sensitive_file`, `_path_is_inside`, `scan_project` with
their full signatures — the head slice showed `_ALWAYS_EXCLUDE` and part of
`_BINARY_EXTS`.

## What works

- Python files over the cap: skeleton in, head out. Redaction proven to run on
  the skeleton (a first-line docstring secret in the fixture is redacted).
- Non-Python oversized files (`.md`, `.ts`, …): unchanged head-truncation.
- Files under the cap: unchanged (sent verbatim).
- Cycle risk scores use on-disk line counts regardless of skeleton on/off.
- Malformed source never aborts a scan (tree-sitter error recovery + the
  never-raise dispatcher).
- All 404 pre-existing tests unchanged and green; 85 new tests (incl. one
  that skeletonises every module in this repo in-process).

## Found along the way: py-tree-sitter 0.26.0 `Node.start_point` segfault

The first renderer used `node.start_point.column` / `.row` for indentation
and line spans. Run over the whole repo, `graphlm . --dry-run` segfaulted
(exit 139) in ~50–100% of runs on `graphlm/diff.py`, `render.py`,
`tests/test_cycles.py`, `test_parser.py`, `test_render.py` — inside
`_PyObject_Malloc`, i.e. heap corruption, and ASLR-dependent (gdb with
randomization off never reproduced it). Isolating by access pattern, 12
subprocess runs each on `diff.py`: a recursive `.children` walk reading
`.type/.start_byte/.end_byte` — 12/12 clean; plus `child_by_field_name()`
— 12/12 clean; plus `.start_point/.end_point` — **12/12 crash**; keeping
the `Parser` alive — no effect. A 200k-iteration loop of `start_point` on
the root node alone does *not* trip it, so the exact upstream mechanism is
not pinned down; the reproducer is the deep walk. The renderer now derives
columns/rows from byte offsets (identical output), a test guards against
reintroducing points in the skeleton section, and the whole-repo probe is
62/62 clean on repeated passes. Worth an upstream issue once reduced
further; graphLM's pre-existing parser code never used points, which is
why it was never hit before.

## What is stubbed / deliberately left out

- **Only Python has a renderer.** `_Resolver.skeleton` defaults to `None`, so
  JS/TS (recognised by extension, no resolver yet) and every other language
  still send the head of the file.
- **Closures are elided.** A `def` nested inside a function body is treated
  as body, not API (only class members are walked). The fixture's `_payload`
  closure is asserted absent.
- **Module-level control flow is dropped** except the `__main__` guard and
  the import-carrying `try:` / `if TYPE_CHECKING:` forms. A `for` loop that
  mutates a constant at import time, `with` blocks, bare calls
  (`app.add_middleware(...)`) do not appear.
- **Skeletons apply only to *oversized* files.** A 3900-char file is still
  sent whole even under a tight `--max-context`.
- Line counts use the repo's existing `newlines + 1` convention (so a file
  ending in a newline counts one more than `wc -l`); kept for consistency
  with `compute_sloc_map`'s tested contract rather than introducing a second
  convention.

## Next increment

1. **JS/TS skeletons** once #42 Phase 1 lands the JS/TS pack: `export`
   statements, `function`/`class`/arrow-const signatures, JSDoc first lines —
   registered as `_Resolver(skeleton=...)` for that pack; the scanner and
   prompt need no change.
2. **Skeletons for all files under a tight budget**: when
   `assemble_pass2_prompt` would drop a file into `truncated_paths`, retry it
   as its skeleton first — the model gets every module's API surface instead
   of losing the lowest-ranked files entirely.
3. A `--skeleton-always` mode (every source file as a skeleton) for very
   large repos, trading body detail for coverage.
