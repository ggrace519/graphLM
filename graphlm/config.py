"""Configuration — frozen Settings dataclass from environment variables."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

from graphlm.llm import LLM_MAX_OUTPUT_TOKENS

# Load .env from the project root (one level up from graphlm/).
load_dotenv()


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
                "GRAPHLM_BASE_URL not set. Set it in .env or pass --base-url."
            )
        if not api_key:
            raise ValueError(
                "GRAPHLM_API_KEY not set. Set it in .env or pass --api-key."
            )
        if not model:
            raise ValueError(
                "GRAPHLM_MODEL not set. Set it in .env or pass --model."
            )

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_context=max_context,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
        )
