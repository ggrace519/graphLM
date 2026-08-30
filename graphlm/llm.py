"""LLM client — OpenAI-compatible HTTP call with response parsing and recovery."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from graphlm.models import CodebaseGraph

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120.0
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0
# Max output tokens requested from the model. The context budget in context.py
# reserves exactly this many tokens for the response, so the two must stay in
# lock-step — import this constant there rather than duplicating the number,
# or an input prompt sized against a smaller reserve can overflow the window
# when the model actually emits up to this many output tokens (#17).
LLM_MAX_OUTPUT_TOKENS = 16000


class GraphLLError(Exception):
    """Base error for graphLM failures."""


class GraphLLErrorUnconfigured(GraphLLError):
    """Required configuration is missing."""


class GraphLLErrorTransport(GraphLLError):
    """Network or HTTP transport failure."""


class GraphLLErrorResponse(GraphLLError):
    """LLM returned a non-2xx response."""


class GraphLLErrorParse(GraphLLError):
    """Response was not valid JSON or didn't match expected schema."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized LLM response."""

    content: str
    model: str


def _extract_json(text: str) -> str | None:
    """Extract JSON from LLM response, stripping markdown code fences if present.

    Tries multiple recovery strategies to handle common LLM output patterns.
    """
    text = text.strip()

    # Try the text as-is first
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove the first fence line
        lines = lines[1:]
        # Remove trailing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
        try:
            json.loads(cleaned)
            return cleaned
        except (json.JSONDecodeError, ValueError):
            pass

    # Find first { and last } in the text
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def call_llm(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    response_format: type[CodebaseGraph] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> CodebaseGraph | str:
    """Call an OpenAI-compatible LLM endpoint and parse the response.

    Args:
        base_url: The API base URL (e.g. https://studio.gracebkp.cloud/v1).
        api_key: The API key for authentication.
        model: The model name to use.
        system_prompt: The system message.
        user_prompt: The user message.
        response_format: If provided, validate the JSON response against
            this Pydantic model.
        timeout: Request timeout in seconds.

    Returns:
        Parsed CodebaseGraph (or the response_format model).

    Raises:
        GraphLLErrorUnconfigured: If configuration is missing.
        GraphLLErrorTransport: If the HTTP call fails.
        GraphLLErrorResponse: If the LLM returns an error response.
        GraphLLErrorParse: If the response cannot be parsed.
    """
    if not base_url or not api_key:
        raise GraphLLErrorUnconfigured("base_url and api_key are required")

    url = base_url.rstrip("/") + "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,  # Low temperature for structured output
        "max_tokens": LLM_MAX_OUTPUT_TOKENS,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=1),
            ) as client:
                response = client.post(url, json=payload, headers=headers)

                if response.status_code != 200:
                    detail = response.text[:500]
                    raise GraphLLErrorResponse(
                        f"LLM returned HTTP {response.status_code}: {detail}"
                    )

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not content:
                    raise GraphLLErrorParse("LLM returned an empty response")

                # Try to parse JSON from the response
                json_text = _extract_json(content)
                if json_text is None:
                    raise GraphLLErrorParse(
                        f"Could not extract JSON from LLM response. "
                        f"Response preview: {content[:200]}"
                    )

                # Validate against schema if requested
                if response_format is not None:
                    try:
                        return response_format.model_validate_json(json_text)
                    except Exception as e:
                        raise GraphLLErrorParse(
                            f"JSON response did not match expected schema: {e}\n"
                            f"Response preview: {json_text[:500]}"
                        )

                # Return raw JSON string if no schema validation requested
                return json_text  # type: ignore[return-value]

        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (2**attempt)
                logger.warning(
                    "LLM connection failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                raise GraphLLErrorTransport(
                    f"LLM connection failed after {_MAX_RETRIES + 1} attempts: {e}"
                ) from e
        except httpx.TimeoutException as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (2**attempt)
                logger.warning(
                    "LLM request timed out (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                )
                time.sleep(delay)
            else:
                raise GraphLLErrorTransport(
                    f"LLM request timed out after {_MAX_RETRIES + 1} attempts"
                ) from e
        except GraphLLError:
            # These are not retriable — propagate immediately
            raise

    # Should not reach here, but just in case
    assert last_error is not None
    raise GraphLLErrorTransport(
        f"LLM call failed: {last_error}"
    ) from last_error
