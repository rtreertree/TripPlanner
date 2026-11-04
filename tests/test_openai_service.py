"""Network-free tests for the official SDK boundary and separate AI roles."""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
import pytest

from trip_planner.config import Config, ConfigurationError
from trip_planner.interpreter import Interpreter
from trip_planner.models import InterpreterResult, PlannerResult, RequestDraft, TripRequest
from trip_planner.openai_service import AIServiceError, OpenAIService
from trip_planner.planner import Planner


def config(**kwargs):
    return Config(api_key="fake-test-key", extractor_model="extractor-test", planner_model="planner-test", **kwargs)


def interpreted():
    return InterpreterResult(
        intent="create",
        request_draft=RequestDraft(destinations=["東京", "Kyoto"], duration_days=7),
        request_updates=RequestDraft(),
        change_instructions="",
        trip_reference=None,
        missing_required_fields=[],
        clarification_question=None,
        assumptions=[],
        assistant_message="A week in Japan.",
    )


def response(parsed=None, *, status="completed", output=None):
    return SimpleNamespace(
        output_parsed=parsed,
        status=status,
        output=output or [],
        model="returned-model",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
    )


def test_official_responses_parse_and_role_metadata():
    client = Mock()
    client.responses.parse.return_value = response(interpreted())
    service = OpenAIService(config(), client)
    result = service.parse(role="interpreter", prompt="Instructions", data={"trip": "東京"}, response_model=InterpreterResult)
    assert result.request_draft.duration_days == 7
    call = client.responses.parse.call_args.kwargs
    assert call["model"] == "extractor-test"
    assert call["text_format"] is InterpreterResult
    assert call["store"] is False
    assert call["input"] == [
        {"role": "system", "content": "Instructions"},
        {"role": "user", "content": '{"trip": "東京"}'},
    ]
    assert service.last_metadata.role == "interpreter"
    assert service.last_metadata.model == "returned-model"
    assert service.last_metadata.usage.total_tokens == 150


def test_sdk_timeout_and_single_retry_are_configured(monkeypatch):
    client = Mock()
    client.responses.parse.return_value = response(interpreted())
    factory = Mock(return_value=client)
    monkeypatch.setattr("trip_planner.openai_service.OpenAI", factory)
    service = OpenAIService(config())
    assert not factory.called  # Construction and offline imports do not call OpenAI.
    service.parse(role="interpreter", prompt="test", data={}, response_model=InterpreterResult)
    factory.assert_called_once_with(api_key="fake-test-key", timeout=90.0, max_retries=1)
    assert client.responses.parse.call_count == 1


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (response(status="incomplete"), "incomplete"),
        (response(), "no structured result"),
        (response(output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])]), "declined"),
        (response({"unrecognized": True}), "invalid structured response"),
    ],
)
def test_bad_responses_raise_without_stale_metadata(reply, message):
    client = Mock()
    client.responses.parse.return_value = reply
    service = OpenAIService(config(), client)
    service.last_metadata = "previous call"
    with pytest.raises(AIServiceError, match=message):
        service.parse(role="interpreter", prompt="test", data={}, response_model=InterpreterResult)
    assert service.last_metadata is None
    assert client.responses.parse.call_count == 1


@pytest.mark.parametrize(
    ("error_type", "status", "message"),
    [
        (AuthenticationError, 401, "authentication"),
        (PermissionDeniedError, 403, "denied"),
        (NotFoundError, 404, "unavailable"),
        (RateLimitError, 429, "quota"),
        (BadRequestError, 400, "Structured Outputs"),
        (APIStatusError, 500, "could not complete"),
    ],
)
def test_provider_errors_are_useful_and_do_not_echo_secrets(error_type, status, message):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    client = Mock()
    client.responses.parse.side_effect = error_type(
        "secret-provider-detail", response=httpx.Response(status, request=request), body=None,
    )
    service = OpenAIService(config(), client)
    with pytest.raises(AIServiceError, match=message) as caught:
        service.parse(role="interpreter", prompt="test", data={}, response_model=InterpreterResult)
    assert "secret-provider-detail" not in str(caught.value)
    assert "fake-test-key" not in str(caught.value)


@pytest.mark.parametrize(("exception", "message"), [(APIConnectionError, "connect"), (APITimeoutError, "timed out")])
def test_network_errors(exception, message):
    client = Mock()
    client.responses.parse.side_effect = exception(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    with pytest.raises(AIServiceError, match=message):
        OpenAIService(config(), client).parse(role="planner", prompt="test", data={}, response_model=PlannerResult)


def test_sdk_parse_validation_errors_become_recoverable():
    client = Mock()
    client.responses.parse.side_effect = json.JSONDecodeError("invalid", "{", 1)
    with pytest.raises(AIServiceError, match="invalid structured response"):
        OpenAIService(config(), client).parse(role="planner", prompt="test", data={}, response_model=PlannerResult)


def test_interpreter_gets_all_labeled_data_and_only_bounded_history():
    service = Mock()
    service.parse.return_value = interpreted()
    service.last_metadata = None
    interpreter = Interpreter(config(timezone="Asia/Bangkok"), service)
    answers = {"Days": "a week", "Destinations": "Tokyo then Kyoto", "Preferences": "Two travelers; actually six days"}
    interpreter.interpret(answers=answers, draft=RequestDraft(), message="Make it five days", history=list(range(30)), pending={"instructions": "Add a museum"})
    call = service.parse.call_args.kwargs
    assert call["role"] == "interpreter"
    assert call["response_model"] is InterpreterResult
    assert call["data"]["labeled_answers"] == answers
    assert call["data"]["recent_conversation"] == list(range(18, 30))
    assert call["data"]["message"] == "Make it five days"
    assert call["data"]["timezone"] == "Asia/Bangkok"
    assert call["data"]["pending_edit"] == {"instructions": "Add a museum"}
    assert len(call["data"]["local_date"]) == 10
    assert "Do not generate an itinerary" in call["prompt"]


def test_planner_receives_normalized_request_separately_from_interpreter():
    service = Mock()
    service.parse.return_value = PlannerResult(itinerary=None, clarification_question="Add a day?", assistant_message="Too far.")
    service.last_metadata = None
    request = TripRequest(trip_name="Japan", destinations=["Tokyo", "Kyoto"], duration_days=1, currency="JPY")
    result = Planner(config(), service).plan(request, instructions="Use trains", feedback="Missing transfer")
    call = service.parse.call_args.kwargs
    assert call["role"] == "planner"
    assert call["response_model"] is PlannerResult
    assert call["data"]["validated_request"] == request.model_dump(mode="json")
    assert "labeled_answers" not in call["data"]
    assert call["data"]["validation_feedback"] == "Missing transfer"
    assert call["data"]["change_instructions"] == "Use trains"
    assert result.clarification_question == "Add a day?"


@pytest.mark.parametrize("response_model", [InterpreterResult, PlannerResult])
def test_real_sdk_builds_strict_schema_and_parses_response_offline(response_model):
    """Exercise the real SDK using an in-memory HTTP transport, never a network."""
    result = interpreted() if response_model is InterpreterResult else PlannerResult(
        itinerary=None, clarification_question="Add a day?", assistant_message="Need more time.",
    )
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "status": "completed", "model": "sdk-test-model",
            "output": [{
                "id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": result.model_dump_json(), "annotations": []}],
            }],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        })

    client = OpenAI(api_key="fake-key", http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    service = OpenAIService(config(), client)
    parsed = service.parse(role="interpreter" if response_model is InterpreterResult else "planner",
                           prompt="test", data={}, response_model=response_model)
    assert parsed == result
    assert service.last_metadata.usage.total_tokens == 30
    format = requests[0]["text"]["format"]
    assert format["type"] == "json_schema"
    assert format["strict"] is True

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(format["schema"])


def test_config_load_respects_environment_without_exposing_key(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=local-secret\nOPENAI_MODEL=from-file\nTRIP_PLANNER_TIMEZONE=Asia/Bangkok\n")
    # dotenv mutates os.environ directly, so isolate the entire mapping.
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setenv("OPENAI_MODEL", "from-process")
    loaded = Config.load(path)
    assert loaded.api_key == "local-secret"
    assert "local-secret" not in repr(loaded)
    assert loaded.extractor_model == loaded.planner_model == "from-process"
    assert loaded.timezone == "Asia/Bangkok"
    loaded.validate_live()


def test_missing_configuration_blocks_only_live_operations():
    empty = Config()
    Interpreter(empty)
    Planner(empty)
    with pytest.raises(ConfigurationError, match="offline example"):
        empty.validate_live()


def test_invalid_timezone_is_actionable():
    with pytest.raises(ConfigurationError, match="IANA timezone"):
        config(timezone="not/a/timezone").validate_live()
