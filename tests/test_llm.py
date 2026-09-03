"""Tests for the LLM client (mocked HTTP, no real LLM calls)."""

import json
from unittest.mock import patch

import pytest
from httpx import Response

from graphlm.llm import (
    CodebaseGraph,
    GraphLLErrorParse,
    GraphLLErrorResponse,
    GraphLLErrorTransport,
    GraphLLErrorUnconfigured,
    call_llm,
)


MOCK_SUCCESS_BODY = {
    "choices": [
        {
            "message": {
                "content": '{"directory_tree": "root/", "import_edges": []}'
            },
            "index": 0,
            "finish_reason": "stop",
        }
    ],
    "model": "test-model",
}

MOCK_INVALID_JSON_BODY = {
    "choices": [
        {"message": {"content": "This is not JSON at all"}, "index": 0}
    ],
}

MOCK_ERROR_BODY = {"error": {"message": "Model not found", "type": "not_found"}}


def _mock_success(httpx_client):
    """Add a successful mock response to the httpx client."""
    httpx_client.respond_with_response(
        Response(200, json=MOCK_SUCCESS_BODY)
    )


def _mock_invalid_json(httpx_client):
    httpx_client.respond_with_response(
        Response(200, json=MOCK_INVALID_JSON_BODY)
    )


def _mock_error_response(httpx_client):
    httpx_client.respond_with_response(
        Response(404, json=MOCK_ERROR_BODY)
    )


class TestCallLlm:
    def test_valid_json_response(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze this.",
            user_prompt="root/\n",
            response_format=CodebaseGraph,
        )
        assert isinstance(result, CodebaseGraph)
        assert result.directory_tree == "root/"
        assert result.import_edges == []

    def test_json_without_schema_validation(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
        )
        # Should return the raw JSON string
        assert "root/" in result

    def test_unconfigured_raises(self):
        with pytest.raises(GraphLLErrorUnconfigured):
            call_llm(
                base_url="",
                api_key="key",
                model="model",
                system_prompt="s",
                user_prompt="u",
            )

    def test_unconfigured_raises_no_api_key(self):
        with pytest.raises(GraphLLErrorUnconfigured):
            call_llm(
                base_url="http://x",
                api_key="",
                model="model",
                system_prompt="s",
                user_prompt="u",
            )

    def test_non_200_response_raises(self, httpx_mock):
        httpx_mock.add_response(status_code=404, json=MOCK_ERROR_BODY)
        with pytest.raises(GraphLLErrorResponse) as exc_info:
            call_llm(
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
                system_prompt="Analyze.",
                user_prompt="root/",
                response_format=CodebaseGraph,
            )
        assert "404" in str(exc_info.value)

    def test_invalid_json_raises(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_INVALID_JSON_BODY)
        with pytest.raises(GraphLLErrorParse) as exc_info:
            call_llm(
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
                system_prompt="Analyze.",
                user_prompt="root/",
                response_format=CodebaseGraph,
            )
        assert "Could not extract JSON" in str(exc_info.value)

    def test_empty_response_raises(self, httpx_mock):
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": ""}, "index": 0}]}
        )
        with pytest.raises(GraphLLErrorParse):
            call_llm(
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
                system_prompt="Analyze.",
                user_prompt="root/",
                response_format=CodebaseGraph,
            )

    def test_schema_validation_failure(self, httpx_mock):
        bad_json = json.dumps({
            "directory_tree": "root/",
            "import_edges": "not_a_list",  # should be a list
        })
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": bad_json}, "index": 0}]}
        )
        with pytest.raises(GraphLLErrorParse) as exc_info:
            call_llm(
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
                system_prompt="Analyze.",
                user_prompt="root/",
                response_format=CodebaseGraph,
            )
        assert "did not match expected schema" in str(exc_info.value)

    def test_strips_code_fences(self, httpx_mock):
        content = '```json\n{"directory_tree": "root/", "import_edges": []}\n```'
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": content}, "index": 0}]}
        )
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
            response_format=CodebaseGraph,
        )
        assert result.directory_tree == "root/"

    def test_strips_text_around_json(self, httpx_mock):
        content = 'Here is the result: {"directory_tree": "root/"}: end'
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": content}, "index": 0}]}
        )
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
            response_format=CodebaseGraph,
        )
        assert result.directory_tree == "root/"

    def test_sends_correct_request(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        call_llm(
            base_url="http://test.local/v1",
            api_key="my-key",
            model="my-model",
            system_prompt="System prompt",
            user_prompt="User prompt",
        )
        request = httpx_mock.get_requests()[-1]
        assert request.url.host == "test.local"
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer my-key"
        body = json.loads(request.content)
        assert body["model"] == "my-model"
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"

    def test_response_format_sent_when_schema_requested(self, httpx_mock):
        """Pass 2 must send response_format so the model emits the full graph (#31).

        Prompt-only instruction is not enough for every served model; without
        the constraint Qwen3.6-35B returned a near-empty object and the run
        produced no graph.
        """
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
        )
        body = json.loads(httpx_mock.get_requests()[-1].content)
        rf = body["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "CodebaseGraph"
        assert "properties" in rf["json_schema"]["schema"]

    def test_response_format_absent_without_schema(self, httpx_mock):
        """Pass 1 (response_format=None) must NOT send the constraint — it wants
        a free-form {"requested_files": [...]} object, not a CodebaseGraph."""
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
        )
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert "response_format" not in body

    def test_400_falls_back_to_prompt_only(self, httpx_mock):
        """An endpoint that rejects response_format (HTTP 400) is retried
        without the constraint, so a prompt-only endpoint still works (#31).
        stream_options is shed first (it is optional telemetry), so the
        prompt-only request is the third one."""
        httpx_mock.add_response(status_code=400, json=MOCK_ERROR_BODY)
        httpx_mock.add_response(status_code=400, json=MOCK_ERROR_BODY)
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
        )
        assert isinstance(result, CodebaseGraph)
        requests = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert len(requests) == 3
        assert "response_format" in requests[0] and "stream_options" in requests[0]
        assert "response_format" in requests[1] and "stream_options" not in requests[1]
        assert "response_format" not in requests[2] and "stream_options" not in requests[2]

    def test_400_sheds_stream_options_but_keeps_schema(self, httpx_mock):
        """A strict endpoint that rejects only stream_options keeps the
        load-bearing response_format constraint on the retry."""
        httpx_mock.add_response(status_code=400, json=MOCK_ERROR_BODY)
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
        )
        assert isinstance(result, CodebaseGraph)
        requests = [json.loads(r.content) for r in httpx_mock.get_requests()]
        assert len(requests) == 2
        assert "stream_options" not in requests[1] and "response_format" in requests[1]

    def test_400_on_pass1_sheds_stream_options(self, httpx_mock):
        """Pass 1 sends no response_format; a 400 there must still retry once
        without stream_options rather than fail outright."""
        httpx_mock.add_response(status_code=400, json=MOCK_ERROR_BODY)
        httpx_mock.add_response(json={"choices": [{"message": {"content": '{"requested_files": []}'}}]})
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
        )
        assert result == '{"requested_files": []}'
        assert len(httpx_mock.get_requests()) == 2

    def test_404_does_not_fall_back(self, httpx_mock):
        """A 404 (missing endpoint/model) is NOT a schema rejection — it must
        surface as an error, not be masked by a constraint-less retry."""
        httpx_mock.add_response(status_code=404, json=MOCK_ERROR_BODY)
        with pytest.raises(GraphLLErrorResponse):
            call_llm(
                base_url="http://test.local/v1",
                api_key="k",
                model="m",
                system_prompt="s",
                user_prompt="u",
                response_format=CodebaseGraph,
            )
        # Only the single 404 request — no constraint-less retry was attempted.
        assert len(httpx_mock.get_requests()) == 1

    def test_retry_on_connection_error(self, httpx_mock):
        """Should retry once on connection error."""
        httpx_mock.add_exception(ConnectionRefusedError("refused"))
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
            response_format=CodebaseGraph,
        )
        assert result.directory_tree == "root/"

    def test_no_retry_on_parse_error(self, httpx_mock):
        """Should not retry on a parse error (non-transport error)."""
        httpx_mock.add_response(json=MOCK_INVALID_JSON_BODY)
        with pytest.raises(GraphLLErrorParse):
            call_llm(
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
                system_prompt="Analyze.",
                user_prompt="root/",
                response_format=CodebaseGraph,
            )
        # Only one request should have been made
        assert len(httpx_mock.get_requests()) == 1

    def test_full_graph_from_llm(self, httpx_mock):
        """Test a complete graph response."""
        full_graph = {
            "directory_tree": "root/\n  src/\n  tests/\n",
            "import_edges": [
                {"from_path": "a.py", "to_path": "b.py", "kind": "import"}
            ],
            "modules": [
                {"path": "a.py", "name": "A", "description": "Module A"}
            ],
            "data_flow": [
                {"source": "A", "destination": "B", "description": "Calls"}
            ],
            "database_schema": None,
            "test_organization": [
                {"file": "test_a.py", "covers": "Module A"}
            ],
            "architecture_notes": [
                {"note": "No ORM"}
            ],
            "quick_reference": [
                {"query": "app", "location": "main.py"}
            ],
        }
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": json.dumps(full_graph)}, "index": 0}]}
        )
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
            response_format=CodebaseGraph,
        )
        assert len(result.import_edges) == 1
        assert len(result.modules) == 1
        assert len(result.data_flow) == 1
        assert result.database_schema is None
        assert len(result.test_organization) == 1
        assert len(result.architecture_notes) == 1
        assert len(result.quick_reference) == 1


def _sse_body(content: str, *, finish_reason: str = "stop", chunk_size: int = 7) -> bytes:
    """Build an OpenAI-style SSE stream body that yields ``content`` split into
    delta chunks, ending with the finish_reason and a [DONE] sentinel."""
    lines: list[bytes] = []
    for i in range(0, len(content), chunk_size):
        piece = content[i : i + chunk_size]
        evt = {"choices": [{"delta": {"content": piece}, "index": 0}]}
        lines.append(b"data: " + json.dumps(evt).encode() + b"\n\n")
    final = {"choices": [{"delta": {}, "index": 0, "finish_reason": finish_reason}]}
    lines.append(b"data: " + json.dumps(final).encode() + b"\n\n")
    lines.append(b"data: [DONE]\n\n")
    return b"".join(lines)


class TestStreaming:
    """The client streams responses (#18); it must reassemble SSE deltas and
    still handle a non-SSE body (existing mocks) transparently."""

    def test_sse_response_reassembled(self, httpx_mock):
        content = '{"directory_tree": "root/", "import_edges": []}'
        httpx_mock.add_response(
            status_code=200,
            content=_sse_body(content, chunk_size=5),
            headers={"content-type": "text/event-stream"},
        )
        result = call_llm(
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            system_prompt="Analyze.",
            user_prompt="root/",
            response_format=CodebaseGraph,
        )
        assert isinstance(result, CodebaseGraph)
        assert result.directory_tree == "root/"
        assert result.import_edges == []

    def test_sse_equals_non_streamed_parse(self, httpx_mock):
        # The reassembled SSE content must parse to the SAME object as the
        # equivalent buffered body — streaming is transport-only.
        content = json.dumps(
            {
                "directory_tree": "root/\n  a.py\n",
                "import_edges": [{"from_path": "a.py", "to_path": "b.py", "kind": "import"}],
                "modules": [{"path": "a.py", "name": "A", "description": "d"}],
            }
        )
        httpx_mock.add_response(status_code=200, content=_sse_body(content))
        streamed = call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
        )
        httpx_mock.add_response(
            status_code=200,
            json={"choices": [{"message": {"content": content}, "index": 0}]},
        )
        buffered = call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
        )
        assert streamed.model_dump() == buffered.model_dump()

    def test_finish_reason_length_raises_truncated(self, httpx_mock):
        from graphlm.llm import GraphLLErrorTruncated

        # A truncated (length-capped) stream must raise a distinct, clear error
        # rather than a confusing parse failure.
        partial = '{"directory_tree": "root/", "import_edges": [{"from_pa'
        httpx_mock.add_response(
            status_code=200, content=_sse_body(partial, finish_reason="length")
        )
        with pytest.raises(GraphLLErrorTruncated):
            call_llm(
                base_url="http://test.local/v1",
                api_key="k",
                model="m",
                system_prompt="s",
                user_prompt="u",
                response_format=CodebaseGraph,
            )

    def test_stream_flag_sent(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
        )
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["stream"] is True

    def test_max_output_tokens_sent_as_max_tokens(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            max_output_tokens=48000,
        )
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["max_tokens"] == 48000


def _sse_body_with_usage(
    content: str, usage: object, *, chunk_size: int = 7
) -> bytes:
    """Like ``_sse_body`` but appends the ``stream_options.include_usage`` chunk
    (``choices: []`` + ``usage``) after the finish chunk, before [DONE] — the
    OpenAI shape."""
    body = _sse_body(content, chunk_size=chunk_size)
    head, _done = body.rsplit(b"data: [DONE]\n\n", 1)
    usage_evt = {"choices": [], "usage": usage}
    return head + b"data: " + json.dumps(usage_evt).encode() + b"\n\ndata: [DONE]\n\n"


class TestUsageCapture:
    """Real token usage from the streamed response (innovation #6): the request
    asks for it via stream_options, the final empty-choices SSE chunk carries
    it, and it reaches the caller through ``on_usage`` — never by changing the
    return type."""

    CONTENT = '{"directory_tree": "root/", "import_edges": []}'

    def _call(self, on_usage=None):
        return call_llm(
            base_url="http://test.local/v1",
            api_key="k",
            model="m",
            system_prompt="s",
            user_prompt="u",
            response_format=CodebaseGraph,
            on_usage=on_usage,
        )

    def test_stream_options_include_usage_sent(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        self._call()
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["stream_options"] == {"include_usage": True}

    def test_sse_usage_chunk_reaches_callback(self, httpx_mock):
        usage = {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290}
        httpx_mock.add_response(
            status_code=200, content=_sse_body_with_usage(self.CONTENT, usage)
        )
        seen: list[dict] = []
        result = self._call(on_usage=seen.append)
        # The usage chunk has empty choices — it must not break content reassembly.
        assert isinstance(result, CodebaseGraph)
        assert result.directory_tree == "root/"
        assert seen == [usage]

    def test_sse_without_usage_chunk_never_calls_back(self, httpx_mock):
        httpx_mock.add_response(status_code=200, content=_sse_body(self.CONTENT))
        seen: list[dict] = []
        self._call(on_usage=seen.append)
        assert seen == []

    def test_non_sse_body_usage_captured(self, httpx_mock):
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        httpx_mock.add_response(json={**MOCK_SUCCESS_BODY, "usage": usage})
        seen: list[dict] = []
        self._call(on_usage=seen.append)
        assert seen == [usage]

    def test_non_sse_body_without_usage_never_calls_back(self, httpx_mock):
        httpx_mock.add_response(json=MOCK_SUCCESS_BODY)
        seen: list[dict] = []
        self._call(on_usage=seen.append)
        assert seen == []

    @pytest.mark.parametrize("bad", ["not-a-dict", 42, ["prompt_tokens", 1], None])
    def test_malformed_usage_ignored_not_raised(self, httpx_mock, bad):
        httpx_mock.add_response(
            status_code=200, content=_sse_body_with_usage(self.CONTENT, bad)
        )
        seen: list[dict] = []
        result = self._call(on_usage=seen.append)
        assert isinstance(result, CodebaseGraph)
        assert seen == []

    def test_no_callback_is_fine_with_usage_present(self, httpx_mock):
        # Existing callers pass no on_usage; a usage chunk must be a no-op.
        httpx_mock.add_response(
            status_code=200,
            content=_sse_body_with_usage(self.CONTENT, {"prompt_tokens": 1}),
        )
        result = self._call()
        assert isinstance(result, CodebaseGraph)

    def test_non_object_sse_chunks_are_skipped(self, httpx_mock):
        # A `data:` line that decodes to a list/string/number is not a chunk;
        # it must neither crash usage capture nor content reassembly.
        body = (
            b"data: [1, 2]\n\n"
            b'data: "just a string"\n\n'
            b"data: 42\n\n"
            + _sse_body_with_usage(self.CONTENT, {"prompt_tokens": 3})
        )
        httpx_mock.add_response(status_code=200, content=body)
        seen: list[dict] = []
        result = self._call(on_usage=seen.append)
        assert isinstance(result, CodebaseGraph)
        assert seen == [{"prompt_tokens": 3}]

    def test_usage_from_chunk_rejects_non_dict_input(self):
        from graphlm.llm import _usage_from_chunk

        assert _usage_from_chunk(["usage"]) is None
        assert _usage_from_chunk({"usage": "x"}) is None
        assert _usage_from_chunk({"usage": {"prompt_tokens": 1}}) == {"prompt_tokens": 1}

    def test_read_streamed_completion_returns_stream_result(self):
        from httpx import Request

        from graphlm.llm import StreamResult, _read_streamed_completion

        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        resp = Response(
            200,
            content=_sse_body_with_usage("hello", usage, chunk_size=2),
            request=Request("POST", "http://test.local/v1/chat/completions"),
        )
        out = _read_streamed_completion(resp)
        assert isinstance(out, StreamResult)
        assert out.content == "hello"
        assert out.usage == usage
