"""Pydantic v2 models for the codebase graph data structure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field


class ImportEdge(BaseModel):
    """A single import/dependency edge between two files."""

    from_path: str = Field(description="Source file path (relative to project root)")
    to_path: str = Field(description="Target file path (relative to project root)")
    kind: str = Field(
        description=(
            "Type of edge: 'import', 'from', 'require', 'static', 'register', "
            "'include', or 'uses'"
        )
    )


class ModuleDescription(BaseModel):
    """A single module/component in the codebase."""

    path: str = Field(description="File or directory path relative to project root")
    name: str = Field(description="Human-readable module name")
    description: str = Field(
        description="One-line description of what the module does"
    )


class DataFlowEdge(BaseModel):
    """A single data flow relationship between components."""

    source: str = Field(description="Source component name or path")
    destination: str = Field(description="Destination component name or path")
    description: str = Field(description="What data flows and in what form")


class DBColumn(BaseModel):
    """A single column in a database table."""

    name: str = Field(description="Column name")
    type: str = Field(description="SQL type (e.g. 'TEXT', 'INTEGER', 'BLOB')")
    constraints: Optional[str] = Field(
        default=None, description="Column constraints (PRIMARY KEY, NOT NULL, etc.)"
    )


class DBTable(BaseModel):
    """A single database table."""

    name: str = Field(description="Table name")
    columns: list[DBColumn] = Field(
        default_factory=list, description="List of columns in the table"
    )
    description: str = Field(
        default="", description="One-line description of what the table stores"
    )


class TestMapping(BaseModel):  # noqa: SLF001
    """A single test file and what it covers."""

    file: str = Field(description="Test file path relative to project root")
    covers: str = Field(description="What functionality this test file verifies")


class ArchitectureNote(BaseModel):
    """A single architecture decision or note."""

    note: str = Field(description="The architecture note or decision")


class Symbol(BaseModel):
    """A public symbol (class, function, or constant) defined in a file."""

    name: str = Field(description="Symbol name")
    kind: str = Field(description="Type: 'class', 'function', 'constant', 'variable'")
    description: str = Field(description="What this symbol does or represents (~100 chars)")


class FileSummary(BaseModel):
    """A short summary of a single analyzed source file."""

    path: str = Field(description="File path relative to project root")
    summary: str = Field(
        description="Concise summary of the file's purpose and key contents (~400 chars max)"
    )
    symbols: list[Symbol] = Field(
        default_factory=list,
        description="Public symbols (classes, functions, constants) defined in this file",
    )


class EntryPoint(BaseModel):
    """A known entry point into the application."""

    path: str = Field(description="File path where the entry point is defined")
    name: str = Field(description="Entry point name (function name, route path, CLI command, etc.)")
    kind: str = Field(
        description="Type of entry point: 'main', 'route', 'cli_command', 'hook', 'plugin', 'factory'"
    )
    description: str = Field(description="What this entry point does and when it's invoked")

class QuickReference(BaseModel):
    """A single quick-reference lookup entry."""

    query: str = Field(
        description="What the user is looking for (e.g. 'where is the app factory')"
    )
    location: str = Field(description="Where to find it (file path or section)")


@dataclass(frozen=True, slots=True)
class Cycle:
    """A single import cycle (strongly connected component) with risk score."""

    nodes: list[str]
    edges: list[ImportEdge]
    length: int
    risk_score: float


# Bump when the persisted metadata shape changes. graphlm reads its own prior
# GRAPH.json (for the fast-follow GRAPH_DIFF), so the stamp is a versioned
# *input* contract, not just output — this integer lets a future format change
# be detected instead of silently misparsed. See DECISIONS.md ADR on the
# self-refreshing stamp.
GRAPH_META_SCHEMA_VERSION = 1


class PassUsage(BaseModel):
    """Token accounting for one LLM pass: what the server billed vs our guess.

    ``prompt_tokens`` / ``completion_tokens`` come from the endpoint's
    ``usage`` object (via ``stream_options.include_usage``) and are ``None``
    when the endpoint sent none. ``estimated_prompt_tokens`` is graphlm's own
    ``estimate_tokens`` figure for the same prompt, so the real-vs-estimated
    ratio — the number that calibrates the ``* 2 // 5`` heuristic (#17) — is
    derivable from the stamp later without re-running anything.
    """

    prompt_tokens: Optional[int] = Field(
        default=None, description="Prompt tokens as counted by the server, or null."
    )
    completion_tokens: Optional[int] = Field(
        default=None, description="Output tokens as counted by the server, or null."
    )
    estimated_prompt_tokens: int = Field(
        description="graphlm's own estimate_tokens() figure for the same prompt."
    )


class RunUsage(BaseModel):
    """Per-pass token usage for one run (both passes optional)."""

    pass1: Optional[PassUsage] = Field(default=None, description="Pass 1 (tree only).")
    pass2: Optional[PassUsage] = Field(default=None, description="Pass 2 (full graph).")


class Faithfulness(BaseModel):
    """How well the LLM's ``import_edges`` agree with the AST ground truth.

    Computed locally by ``graphlm.faithfulness.score`` over ``(from, to)``
    pairs. ``precision`` = matched / LLM edges the parser could have seen;
    ``recall`` = matched / AST edges. Either is ``None`` when its denominator
    is zero. Absent (``meta.faithfulness`` null) when AST was off or on a
    dry run (no LLM edges to score).
    """

    precision: Optional[float] = Field(
        default=None, description="matched / comparable LLM edges, or null if none."
    )
    recall: Optional[float] = Field(
        default=None, description="matched / AST edges, or null if none."
    )
    llm_edges: int = Field(description="LLM import edges the AST could have seen.")
    ast_edges: int = Field(description="AST (deterministic) edges.")
    matched: int = Field(description="Edges present on both sides.")


class GraphMeta(BaseModel):
    """Provenance stamp: when the graph was generated and against which commit.

    Filled locally by ``generate_graph`` after pass 2 (never emitted by the
    LLM, like ``directory_tree`` and ``deterministic_edges``). The
    ``GRAPH.md`` refresh directive is *rendered from* this, so the two cannot
    drift. ``commit_sha`` is ``None`` for a non-git project — that is a normal
    state, not an error, and is preserved (not dropped) in ``GRAPH.json`` so a
    reader can tell "no git tracking" from "old format, field absent".
    """

    schema_version: int = Field(
        default=GRAPH_META_SCHEMA_VERSION,
        description="Metadata format version (for reading prior graphs).",
    )
    created_at: str = Field(
        description="ISO 8601 UTC timestamp when the graph was generated. "
        "Human context only — never the staleness trigger."
    )
    commit_sha: Optional[str] = Field(
        default=None,
        description="Git HEAD commit SHA the graph was generated against, or "
        "null if the project is not a git repo (or has no commits). Staleness "
        "= this differs from the repo's current HEAD.",
    )
    graphlm_version: Optional[str] = Field(
        default=None, description="graphlm package version that generated the graph."
    )
    # Run telemetry (innovation #6). Both are ADDITIVE and optional: an older
    # GRAPH.json without them still validates (defaults to None) and the
    # meaning of the existing fields is unchanged, so GRAPH_META_SCHEMA_VERSION
    # stays at 1 — ADR-001 bumps it only when the *meaning* changes.
    usage: Optional[RunUsage] = Field(
        default=None,
        description="Real vs estimated token usage per pass. Null on a dry run "
        "or when the endpoint reported no usage.",
    )
    faithfulness: Optional[Faithfulness] = Field(
        default=None,
        description="LLM import_edges vs AST deterministic_edges agreement. "
        "Null when AST was off or on a dry run.",
    )


class CodebaseGraph(BaseModel):
    """The complete codebase graph as produced by the LLM."""

    directory_tree: str = Field(
        description="Annotated directory tree of the project"
    )
    import_edges: list[ImportEdge] = Field(
        default_factory=list, description="Import/dependency edges between files"
    )
    modules: list[ModuleDescription] = Field(
        default_factory=list, description="Modules and what they do"
    )
    data_flow: list[DataFlowEdge] = Field(
        default_factory=list, description="Data flow between components"
    )
    database_schema: Optional[list[DBTable]] = Field(
        default=None, description="Database tables and columns, or null if no DB"
    )
    test_organization: list[TestMapping] = Field(
        default_factory=list, description="Test file to coverage mapping"
    )
    architecture_notes: list[ArchitectureNote] = Field(
        default_factory=list, description="Architecture decisions and notes"
    )
    file_summaries: list[FileSummary] = Field(
        default_factory=list, description="Short summaries (~400 chars) of analyzed source files"
    )
    entry_points: list[EntryPoint] = Field(
        default_factory=list, description="Known application entry points (main, routes, CLI commands, etc.)"
    )
    quick_reference: list[QuickReference] = Field(
        default_factory=list, description="Quick-reference lookup table"
    )
    deterministic_edges: list[ImportEdge] | None = Field(
        default=None,
        description="Import edges derived from AST parsing (deterministic, not LLM-generated)",
    )
    import_cycles: list[Cycle] = Field(
        default_factory=list,
        description="Import cycles (strongly connected components) with risk scores",
    )
    meta: Optional[GraphMeta] = Field(
        default=None,
        description="Provenance stamp (generation time, commit SHA, version). "
        "Filled locally, not by the LLM. Null on graphs built without it "
        "(older format or library callers) — the renderer omits the refresh "
        "directive in that case.",
    )
