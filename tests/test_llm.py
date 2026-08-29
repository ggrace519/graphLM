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
