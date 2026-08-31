"""Configuration — frozen Settings dataclass from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from graphlm.llm import LLM_MAX_OUTPUT_TOKENS


def _user_config_path() -> Path:
    """User-level config path: ``$XDG_CONFIG_HOME/graphlm/.env`` when
    ``$XDG_CONFIG_HOME`` is set and non-empty, else ``~/.config/graphlm/.env``.

    Reads the env var at call time (not import time) so it stays testable.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "graphlm" / ".env"


def _load_env_files() -> None:
    """Populate ``os.environ`` from .env files without clobbering real env vars.

    Resolution precedence (first non-empty wins), highest to lowest:

    1. the real shell environment (already in ``os.environ`` — never touched);
    2. the project ``.env`` (searched from the CURRENT WORKING DIRECTORY
       upward — ``usecwd=True``, so an *installed* graphlm sees the user's
       project, not its own site-packages tree — #45);
    3. the user-level ``~/.config/graphlm/.env`` (or
       ``$XDG_CONFIG_HOME/graphlm/.env``) — a global fallback for a
       ``uv tool install`` where no project ``.env`` is on the path (#45);
    4. the built-in defaults in :class:`Settings`.

    ``load_dotenv(override=False)`` never overwrites a variable already present,
    so loading the lower-precedence source second yields exactly the order
    above. Bare ``load_dotenv()`` / ``find_dotenv()`` (no ``usecwd``) searches
    upward from *this module's* directory, so an installed graphlm would miss
    the user's project ``.env`` entirely — that is why we pass ``usecwd=True``
    and guard the empty ("not found") result: ``load_dotenv("")`` would fall
    back to that broken frame-based search.
    """
    project_env = find_dotenv(usecwd=True)  # "" when none found on the path
    if project_env:
        load_dotenv(project_env, override=False)

    user_env = _user_config_path()
    if user_env.is_file():
        load_dotenv(user_env, override=False)


_load_env_files()


# Default maximum context window (tokens) — ~128k with room for output
_DEFAULT_MAX_CONTEXT = 120000
# Default LLM request timeout (seconds) — generous because pass 2 is streamed
# and a large project's generation can take minutes (#18). Mirrors
# llm._DEFAULT_TIMEOUT; overridable via GRAPHLM_TIMEOUT / --timeout.
_DEFAULT_TIMEOUT = 300.0
# Default max output tokens — sourced from llm.py so the two cannot drift. Sized
# from measurement (a real project's full graph needs ~18k output tokens — #18);
# overridable via GRAPHLM_MAX_OUTPUT_TOKENS / --max-output-tokens.
_DEFAULT_MAX_OUTPUT_TOKENS = LLM_MAX_OUTPUT_TOKENS


@dataclass(frozen=True, slots=True)
class Settings:
    """OpenAI-compatible LLM endpoint configuration from env vars."""

    base_url: str
    api_key: str
    model: str
    max_context: int = _DEFAULT_MAX_CONTEXT
    timeout: float = _DEFAULT_TIMEOUT
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from GRAPHLM_* environment variables."""
        import os

        base_url = os.environ.get("GRAPHLM_BASE_URL", "")
        api_key = os.environ.get("GRAPHLM_API_KEY", "")
        model = os.environ.get("GRAPHLM_MODEL", "")
        max_context = int(os.environ.get("GRAPHLM_MAX_CONTEXT", _DEFAULT_MAX_CONTEXT))
        timeout = float(os.environ.get("GRAPHLM_TIMEOUT", _DEFAULT_TIMEOUT))
        max_output_tokens = int(
            os.environ.get("GRAPHLM_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
        )

        if not base_url:
            raise ValueError(
                "GRAPHLM_BASE_URL not set. Export it, set it in a project "
                ".env or ~/.config/graphlm/.env, or pass --base-url."
            )
        if not api_key:
            raise ValueError(
                "GRAPHLM_API_KEY not set. Export it, set it in a project "
                ".env or ~/.config/graphlm/.env, or pass --api-key."
            )
        if not model:
            raise ValueError(
                "GRAPHLM_MODEL not set. Export it, set it in a project "
                ".env or ~/.config/graphlm/.env, or pass --model."
            )

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_context=max_context,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
        )
