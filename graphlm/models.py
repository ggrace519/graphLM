"""Pydantic v2 models for the codebase graph data structure."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ImportEdge(BaseModel):
    """A single import/dependency edge between two files."""

    from_path: str = Field(description="Source file path (relative to project root)")
    to_path: str = Field(description="Target file path (relative to project root)")
    kind: str = Field(
        description="Type of edge: 'import', 'from', 'register', 'include', or 'uses'"
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
