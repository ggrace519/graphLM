"""LLM client — OpenAI-compatible HTTP call with response parsing and recovery."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from graphlm.models import CodebaseGraph

logger = logging.getLogger(__name__)

# Default request timeout (seconds). Generous because pass 2 is streamed: a
# large project's full CodebaseGraph JSON legitimately takes ~200s to generate
# on a mid-size model. Overridable via GRAPHLM_TIMEOUT / --timeout (#18).
_DEFAULT_TIMEOUT = 300.0
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0
# Default max output tokens requested from the model. Sized from measurement:
# a real project's full CodebaseGraph JSON needs ~18k output tokens (the argus
# repo, once the directory-tree echo was removed — #18), so the previous 16000
# truncated it mid-graph. 32000 fits that with margin; the endpoint accepts far
# more. Configurable via GRAPHLM_MAX_OUTPUT_TOKENS / --max-output-tokens.
#
# The pass-2 context budget in context.py reserves exactly this many tokens for
# the response, so the two MUST stay in lock-step: assemble_pass2_prompt takes
# the effective value as a parameter (defaulting to this constant). Raising it
# grows the output reserve and shrinks the input budget in step — correct, since
# more output leaves less room for input (#17).
LLM_MAX_OUTPUT_TOKENS = 32000


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


class GraphLLErrorTruncated(GraphLLErrorParse):
    """The model hit its max_tokens ceiling and returned truncated output."""


def _read_streamed_completion(
    response: httpx.Response, *, max_output_tokens: int = LLM_MAX_OUTPUT_TOKENS
) -> str:
    """Read a streamed (SSE) chat-completions response into its content string.

    The request is sent with ``stream: true`` so the response arrives as a
    sequence of ``data: {json}`` lines (OpenAI SSE), terminated by ``data:
    [DONE]``. Streaming is what keeps a long generation alive past a proxy's
    read timeout (Cloudflare 524 — #18): each delta resets the edge timer,
    whereas a single buffered response can exceed it before the first byte.

    Tolerates a **non-SSE** body too: if no ``data:`` line is ever seen, the
    accumulated text is returned as-is and parsed as a plain chat-completions
    JSON object by the caller. This keeps non-streaming test mocks (and any
    server that ignores ``stream``) working unchanged.

    Raises GraphLLErrorTruncated if the model stopped on ``finish_reason ==
    "length"`` (output hit max_tokens — the JSON is truncated and unparseable),
    so that surfaces as a clear "graph too large" error rather than a confusing
    parse failure.
    """
    parts: list[str] = []
    raw: list[str] = []
    saw_sse = False
    finish_reason: str | None = None

    for line in response.iter_lines():
        raw.append(line)
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            continue
        saw_sse = True
        data = stripped[len("data:") :].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        piece = delta.get("content")
        if piece:
            parts.append(piece)
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    if finish_reason == "length":
        raise GraphLLErrorTruncated(
            "LLM output hit the max_tokens ceiling and was truncated "
            f"({max_output_tokens} tokens) — the project is too large to graph "
            "in one response. Raise --max-output-tokens (GRAPHLM_MAX_OUTPUT_TOKENS) "
            "or reduce scope (e.g. --max-pass2-files)."
        )

    if not saw_sse:
        # Non-SSE body (e.g. a test mock or a server ignoring stream): parse the
        # whole body as a plain chat-completions JSON object and pull content out
        # of it, so this path yields the same content string as the SSE path.
        body = "".join(raw)
        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"] or ""
        except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
            # Not a recognizable completion object — return raw for the caller's
            # JSON-recovery to attempt (preserves prior lenient behavior).
            return body
    return "".join(parts)


def call_llm(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    response_format: type[CodebaseGraph] | None = None,
    timeout: float | None = None,
    max_output_tokens: int = LLM_MAX_OUTPUT_TOKENS,
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
        timeout: Request timeout in seconds (default 300; streamed responses can
            legitimately take several minutes on a large project — #18).

    The response is streamed (``stream: true``) and reassembled; a server that
    ignores the flag and returns a normal body is handled transparently. Both
    passes stream for a single response-reading path.

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

    if timeout is None:
        timeout = _DEFAULT_TIMEOUT

    url = base_url.rstrip("/") + "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,  # Low temperature for structured output
        "max_tokens": max_output_tokens,
        # Stream so a long generation stays alive past proxy read timeouts —
        # a non-streamed pass-2 for a large repo hit Cloudflare's 524 at ~125s
        # while the origin was still generating (#18). A server that ignores
        # this flag returns a normal body, which _read_streamed_completion
        # handles transparently.
        "stream": True,
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
                with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        # Status is known before any body bytes. A non-200 here
                        # (e.g. the 524 that motivated streaming) is NOT retried
                        # — GraphLLError propagates via the except clause below,
                        # so we don't burn minutes re-waiting on a hard failure.
                        response.read()
                        detail = response.text[:500]
                        raise GraphLLErrorResponse(
                            f"LLM returned HTTP {response.status_code}: {detail}"
                        )

                    content = _read_streamed_completion(
                        response, max_output_tokens=max_output_tokens
                    )

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

        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            # Mid-stream transport failures (a dropped connection after partial
            # deltas). Retriable — the whole generation re-runs and any partial
            # content is discarded; a partial stream is never parsed (#18).
            httpx.ReadError,
            httpx.RemoteProtocolError,
            OSError,
        ) as e:
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
