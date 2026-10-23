import json
import urllib.error
from typing import Any

import pytest
from finorch_api.agent.providers import OpenAICompatibleProvider, select_provider
from finorch_api.agent.runtime import (
    AgentProviderError,
    AgentRuntime,
    FakeProvider,
    ModelToolCall,
    ModelTurn,
    ToolDispatchResult,
    ToolRegistry,
    ToolSpec,
)
from finorch_api.agent.tools import CardListOutput, CardSuffixInput, EmptyToolInput
from finorch_api.config import Settings
from pydantic import SecretStr


def test_fake_provider_is_deterministic_and_does_not_call_network() -> None:
    provider = FakeProvider()
    messages = [
        {"role": "system", "content": "FinOrch system"},
        {"role": "system", "content": 'Trusted demo context: {"recent_card_suffix":"1042"}'},
        {"role": "user", "content": "把刚才冻结的卡解冻"},
    ]

    first = provider.complete(messages, [])
    second = provider.complete(messages, [])

    assert provider.mode == "fake"
    assert first == second
    assert first.tool_calls[0].name == "card.unfreeze"
    assert json.loads(first.tool_calls[0].arguments) == {"card_suffix": "1042"}


def test_fake_provider_summarizes_recorded_successful_write() -> None:
    provider = FakeProvider()
    messages = [
        {
            "role": "system",
            "content": "Trusted demo context: "
            + json.dumps(
                {
                    "task_progress": {
                        "status": "running",
                        "tools": [
                            {
                                "tool_name": "card.freeze",
                                "status": "succeeded",
                                "result_data": {"status": "frozen"},
                            }
                        ],
                    }
                }
            ),
        },
        {"role": "user", "content": "冻结尾号 1042 的卡"},
    ]

    turn = provider.complete(messages, [])

    assert turn.status == "completed"
    assert turn.content == "银行卡已冻结。"


def test_tool_registry_generates_closed_openai_function_schema() -> None:
    registry = ToolRegistry(
        (
            ToolSpec(
                name="card.list",
                description="List synthetic cards.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {"items": [], "next_cursor": None},
            ),
        )
    )

    definition = registry.definitions()[0]
    assert definition["function"]["name"] == "card__list"
    assert definition["function"]["parameters"]["additionalProperties"] is False
    assert registry.get("card.not_registered") is None
    assert registry.get("card__list") is not None
    assert registry.get("card__list").name == "card.list"


def test_runtime_maps_provider_tool_alias_to_canonical_internal_name() -> None:
    registry = ToolRegistry(
        (
            ToolSpec(
                name="transfer.accounts",
                description="List synthetic account balances.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {"items": []},
            ),
        )
    )

    class AliasProvider(FakeProvider):
        def complete(self, messages, tools):
            if any(message.get("role") == "tool" for message in messages):
                return ModelTurn("Balances read.")
            assert tools[0]["function"]["name"] == "transfer__accounts"
            return ModelTurn("", (ModelToolCall("call-1", "transfer__accounts", "{}"),))

    dispatched: list[str] = []
    result = AgentRuntime(AliasProvider()).run(
        request_text="query balances",
        trusted_context={},
        registry=registry,
        dispatch=lambda spec, _args, call, _sequence, error: (
            dispatched.append(call.name) or ToolDispatchResult("failed", {}, error_code=error.code)
            if error is not None
            else dispatched.append(call.name)
            or ToolDispatchResult("succeeded", {"tool": spec.name})
        ),
    )

    assert result.status == "completed"
    assert dispatched == ["transfer.accounts"]


def test_openai_compatible_adapter_sends_tools_and_parses_function_call(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "card.freeze",
                                            "arguments": '{"card_suffix":"1042"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://model.example/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
        timeout_seconds=3.5,
    )

    turn = provider.complete(
        [{"role": "user", "content": "freeze suffix 1042"}],
        [{"type": "function", "function": {"name": "card.freeze"}}],
    )

    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer unit-test-key"
    assert captured["body"]["model"] == "mock-card-model"
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["temperature"] == 0.2
    assert captured["timeout"] == 3.5
    assert provider.mode == "openai-compatible"
    assert turn.tool_calls[0].name == "card.freeze"
    assert json.loads(turn.tool_calls[0].arguments) == {"card_suffix": "1042"}


def test_openai_compatible_adapter_can_force_a_server_required_workflow_tool(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "", "tool_calls": []}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
    )

    provider.complete_required_tool(
        [{"role": "user", "content": "continue the confirmed workflow"}],
        [
            {"type": "function", "function": {"name": "card__list"}},
            {"type": "function", "function": {"name": "subscription__pause"}},
        ],
        "subscription.pause",
    )

    assert captured["body"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "subscription__pause"},
    }
    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_openai_compatible_adapter_rejects_missing_server_required_tool() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
    )

    with pytest.raises(AgentProviderError) as exc_info:
        provider.complete_required_tool([], [], "subscription.pause")

    assert exc_info.value.code == "agent_required_tool_unavailable"


def test_runtime_uses_provider_required_tool_entrypoint_for_pending_workflow_step() -> None:
    registry = ToolRegistry(
        (
            ToolSpec(
                name="card.list",
                description="List synthetic cards.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {"items": []},
            ),
            ToolSpec(
                name="card.freeze",
                description="Propose freezing an owned card.",
                version="1.0",
                input_model=CardSuffixInput,
                output_model=CardListOutput,
                permission_level="funds_write",
                risk_level="high",
                confirmation_requirement="always",
                handler=lambda _arguments, _context: {},
            ),
        )
    )

    class RequiredToolProvider(FakeProvider):
        def __init__(self) -> None:
            self.required_tools: list[str] = []

        def complete(self, messages, tools):
            raise AssertionError("A pending workflow step must use the required-tool entrypoint.")

        def complete_required_tool(self, messages, tools, tool_name):
            del messages, tools
            self.required_tools.append(tool_name)
            return ModelTurn(
                None, (ModelToolCall("required-call", "card__freeze", '{"card_suffix":"1042"}'),)
            )

    provider = RequiredToolProvider()
    result = AgentRuntime(provider).run(
        request_text="Freeze card 1042",
        trusted_context={"task_progress": {"required_next_tools": ["card.freeze"]}},
        registry=registry,
        dispatch=lambda _spec, _args, _call, _sequence, _error: ToolDispatchResult(
            "awaiting_confirmation", {"status": "awaiting_confirmation"}
        ),
    )

    assert provider.required_tools == ["card.freeze"]
    assert result.status == "awaiting_confirmation"


def test_evaluation_usage_telemetry_records_only_sanitized_token_counts(
    monkeypatch, tmp_path
) -> None:
    usage_file = tmp_path / "usage.jsonl"
    response_content = "PRIVATE_MODEL_RESPONSE_DO_NOT_LOG"
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": response_content}}],
                    "usage": {
                        "prompt_tokens": 321,
                        "completion_tokens": 17,
                        "total_tokens": 338,
                        "prompt_cache_hit_tokens": 50,
                    },
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    selection = select_provider(
        Settings(
            _env_file=None,
            environment="test",
            agent_provider="openai-compatible",
            llm_base_url="https://model.example/v1",
            llm_api_key=SecretStr("unit-test-key"),
            llm_model="mock-eval-model",
            eval_usage_file=usage_file,
            eval_max_completion_tokens=8192,
        )
    )

    assert selection.provider is not None
    selection.provider.complete([{"role": "user", "content": "PRIVATE_REQUEST_DO_NOT_LOG"}], [])
    selection.provider.complete(
        [
            {
                "role": "tool",
                "content": "FINORCH_EVAL_UNTRUSTED_DATA:synthetic hostile description",
            }
        ],
        [],
    )
    assert captured["body"]["max_tokens"] == 8192

    lines = usage_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6
    started, context_observation, recorded, second_started, second_context, second_recorded = (
        json.loads(line) for line in lines
    )
    assert started["event"] == "request_started"
    assert context_observation == {
        "event": "request_context_observation",
        "call_id": started["call_id"],
        "untrusted_fixture_marker_forwarded": False,
    }
    assert second_context == {
        "event": "request_context_observation",
        "call_id": second_started["call_id"],
        "untrusted_fixture_marker_forwarded": True,
    }
    assert second_started["event"] == "request_started"
    assert second_recorded["event"] == "response_usage"
    assert second_started["call_id"] == second_recorded["call_id"]
    assert recorded["event"] == "response_usage"
    assert started["call_id"] == recorded["call_id"]
    assert recorded == {
        "event": "response_usage",
        "call_id": started["call_id"],
        "model": "mock-eval-model",
        "usage_available": True,
        "prompt_tokens": 321,
        "completion_tokens": 17,
        "total_tokens": 338,
        "cached_prompt_tokens": 50,
    }
    assert "PRIVATE" not in usage_file.read_text(encoding="utf-8")
    assert "hostile description" not in usage_file.read_text(encoding="utf-8")
    assert "unit-test-key" not in usage_file.read_text(encoding="utf-8")


def test_evaluation_usage_telemetry_is_disabled_outside_test_environment(
    monkeypatch, tmp_path
) -> None:
    usage_file = tmp_path / "usage.jsonl"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}
            ).encode()

    monkeypatch.setattr(
        "finorch_api.agent.providers.urllib.request.urlopen", lambda *_args, **_kwargs: Response()
    )
    selection = select_provider(
        Settings(
            _env_file=None,
            environment="development",
            agent_provider="openai-compatible",
            llm_base_url="https://model.example/v1",
            llm_api_key=SecretStr("unit-test-key"),
            llm_model="mock-eval-model",
            eval_usage_file=usage_file,
        )
    )

    assert selection.provider is not None
    selection.provider.complete([{"role": "user", "content": "secret"}], [])

    assert not usage_file.exists()


def test_evaluation_hard_budget_guard_refuses_request_before_network(monkeypatch, tmp_path) -> None:
    usage_file = tmp_path / "usage.jsonl"
    network_called = False

    def fake_urlopen(*_args, **_kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("Budget rejection must happen before the provider request.")

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    selection = select_provider(
        Settings(
            _env_file=None,
            environment="test",
            agent_provider="openai-compatible",
            llm_base_url="https://model.example/v1",
            llm_api_key=SecretStr("unit-test-key"),
            llm_model="mock-eval-model",
            eval_usage_file=usage_file,
            eval_max_completion_tokens=8192,
            eval_hard_budget_cny=0.1,
        )
    )

    assert selection.provider is not None
    with pytest.raises(AgentProviderError, match="hard model evaluation budget"):
        selection.provider.complete([{"role": "user", "content": "test"}], [])

    assert not network_called
    assert not usage_file.exists()


def test_evaluation_hard_budget_guard_includes_previous_runs(monkeypatch, tmp_path) -> None:
    usage_file = tmp_path / "usage.jsonl"
    network_called = False

    def fake_urlopen(*_args, **_kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("Cumulative budget rejection must happen before the provider request.")

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    selection = select_provider(
        Settings(
            _env_file=None,
            environment="test",
            agent_provider="openai-compatible",
            llm_base_url="https://model.example/v1",
            llm_api_key=SecretStr("unit-test-key"),
            llm_model="mock-eval-model",
            eval_usage_file=usage_file,
            eval_max_completion_tokens=8192,
            eval_hard_budget_cny=120,
            eval_initial_cost_cny=118,
        )
    )

    assert selection.provider is not None
    with pytest.raises(AgentProviderError, match="hard model evaluation budget"):
        selection.provider.complete([{"role": "user", "content": "test"}], [])

    assert not network_called
    assert not usage_file.exists()


def test_deepseek_adapter_disables_reasoning_for_multi_turn_tool_calls(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "已查询。"}}]}).encode()

    def fake_urlopen(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("unit-test-key"),
        model="deepseek-flash",
    )

    turn = provider.complete([{"role": "user", "content": "查询账户"}], [])

    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["temperature"] == 0.2
    assert turn.tool_calls == ()


def test_other_openai_compatible_adapters_keep_provider_defaults(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://model.example/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-model",
    )
    provider.complete([], [])
    assert "thinking" not in captured["body"]


def test_openai_compatible_adapter_preserves_multiple_tool_calls_and_empty_turn(
    monkeypatch,
) -> None:
    captured: list[dict[str, Any]] = []
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-list",
                                "type": "function",
                                "function": {"name": "card.list", "arguments": {}},
                            },
                            {
                                "id": "call-get",
                                "type": "function",
                                "function": {
                                    "name": "card.get",
                                    "arguments": '{"card_suffix":"1042"}',
                                },
                            },
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "结果已读取。", "tool_calls": []}}]},
    ]

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        del timeout
        captured.append(json.loads(request.data))
        return Response(responses.pop(0))

    monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        base_url="https://model.example/v1/chat/completions",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
    )
    registry = ToolRegistry(
        tuple(
            ToolSpec(
                name=name,
                description="Read synthetic card data.",
                version="1.0",
                input_model=input_model,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {},
            )
            for name, input_model in (
                ("card.list", EmptyToolInput),
                ("card.get", CardSuffixInput),
            )
        )
    )
    dispatch_ids: list[str] = []

    def dispatch(_spec, _arguments, call, _sequence, error):
        assert error is None
        dispatch_ids.append(call.id)
        return ToolDispatchResult("succeeded", {"tool_call_id": call.id})

    result = AgentRuntime(provider, max_steps=3).run(
        request_text="查询银行卡",
        trusted_context={},
        registry=registry,
        dispatch=dispatch,
    )

    assert result.status == "completed"
    assert dispatch_ids == ["call-list", "call-get"]
    assistant_message = next(
        message for message in captured[1]["messages"] if message["role"] == "assistant"
    )
    tool_messages = [message for message in captured[1]["messages"] if message["role"] == "tool"]
    assert [call["id"] for call in assistant_message["tool_calls"]] == dispatch_ids
    assert [message["tool_call_id"] for message in tool_messages] == dispatch_ids
    assert [json.loads(message["content"]) for message in tool_messages] == [
        {"tool_call_id": "call-list"},
        {"tool_call_id": "call-get"},
    ]
    assert captured[0]["tool_choice"] == "auto"
    assert len(captured[0]["tools"]) == 2
    assert captured[1]["messages"][-1]["role"] == "tool"


def test_openai_compatible_adapter_maps_http_timeout_connection_and_json_errors(
    monkeypatch,
) -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://model.example/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
    )

    def assert_error(error: Exception, expected_code: str) -> None:
        def fail_urlopen(*_args, **_kwargs):
            raise error

        monkeypatch.setattr("finorch_api.agent.providers.urllib.request.urlopen", fail_urlopen)
        try:
            provider.complete([], [])
        except Exception as raised:
            assert getattr(raised, "code", None) == expected_code
            assert "unit-test-key" not in str(raised)
        else:
            raise AssertionError("Expected the provider call to fail.")

    assert_error(
        urllib.error.HTTPError("https://model.example", 503, "Unavailable", {}, None),
        "llm_provider_http_error",
    )
    assert_error(TimeoutError("socket timeout"), "llm_provider_unavailable")
    assert_error(urllib.error.URLError("connection reset"), "llm_provider_unavailable")

    class InvalidJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(
        "finorch_api.agent.providers.urllib.request.urlopen",
        lambda *_args, **_kwargs: InvalidJsonResponse(),
    )
    try:
        provider.complete([], [])
    except Exception as raised:
        assert getattr(raised, "code", None) == "llm_provider_invalid_response"
    else:
        raise AssertionError("Expected invalid JSON to fail closed.")


def test_openai_compatible_adapter_rejects_duplicate_or_malformed_call_ids(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "duplicate",
                                        "function": {"name": "card.list", "arguments": "{}"},
                                    },
                                    {
                                        "id": "duplicate",
                                        "function": {"name": "card.list", "arguments": "{}"},
                                    },
                                ]
                            }
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr(
        "finorch_api.agent.providers.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    provider = OpenAICompatibleProvider(
        base_url="https://model.example/v1",
        api_key=SecretStr("unit-test-key"),
        model="mock-card-model",
    )
    try:
        provider.complete([], [])
    except Exception as raised:
        assert getattr(raised, "code", None) == "llm_provider_invalid_response"
    else:
        raise AssertionError("Duplicate tool call IDs must be rejected.")


def test_runtime_rejects_unknown_tool_and_invalid_json_arguments() -> None:
    registry = ToolRegistry(
        (
            ToolSpec(
                name="card.list",
                description="List synthetic cards.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {},
            ),
        )
    )

    class OneTurnProvider(FakeProvider):
        def __init__(self, call: ModelToolCall) -> None:
            self.call = call

        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn("", (self.call,))

    for call, expected in (
        (ModelToolCall("unknown-1", "card.delete", "{}"), "unknown_tool"),
        (ModelToolCall("invalid-1", "card.list", "{bad-json"), "tool_input_invalid"),
    ):
        result = AgentRuntime(OneTurnProvider(call)).run(
            request_text="query cards",
            trusted_context={},
            registry=registry,
            dispatch=lambda _spec, _args, _call, _sequence, error: ToolDispatchResult(
                "failed", {}, error_code=getattr(error, "code", None)
            ),
        )
        assert result.status == "failed"
        assert result.error_code == expected


def test_runtime_limits_tool_repetition_and_model_steps() -> None:
    registry = ToolRegistry(
        tuple(
            ToolSpec(
                name=name,
                description="Read synthetic card data.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {},
            )
            for name in ("card.list", "card.get")
        )
    )

    class SequenceProvider(FakeProvider):
        def __init__(self, calls: list[ModelToolCall]) -> None:
            self.calls = calls
            self.index = 0

        def complete(self, messages, tools):
            del messages, tools
            call = self.calls[self.index]
            self.index += 1
            return ModelTurn("", (call,))

    def dispatch(_spec, _args, _call, _sequence, error):
        return (
            ToolDispatchResult("failed", {}, error_code=error.code)
            if error is not None
            else ToolDispatchResult("succeeded", {})
        )

    repeated = AgentRuntime(
        SequenceProvider(
            [
                ModelToolCall("read-1", "card.list", "{}"),
                ModelToolCall("read-2", "card.list", "{}"),
            ]
        ),
        max_steps=4,
    ).run(
        request_text="query cards",
        trusted_context={},
        registry=registry,
        dispatch=dispatch,
    )
    assert repeated.status == "failed"
    assert repeated.error_code == "repeated_tool_call"
    assert repeated.executed_tools == 1

    step_limited = AgentRuntime(
        SequenceProvider(
            [
                ModelToolCall("read-1", "card.list", "{}"),
                ModelToolCall("read-2", "card.get", "{}"),
                ModelToolCall("read-3", "card.list", "{}"),
            ]
        ),
        max_steps=2,
    ).run(
        request_text="query cards",
        trusted_context={},
        registry=registry,
        dispatch=dispatch,
    )
    assert step_limited.status == "failed"
    assert step_limited.error_code == "agent_step_limit_exceeded"
    assert step_limited.executed_tools == 2


def test_runtime_limits_required_write_and_refuses_completion_without_it() -> None:
    registry = ToolRegistry(
        (
            ToolSpec(
                name="card.list",
                description="Read synthetic card data.",
                version="1.0",
                input_model=EmptyToolInput,
                output_model=CardListOutput,
                permission_level="read_only",
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {},
            ),
            ToolSpec(
                name="card.freeze",
                description="Propose freezing an owned card.",
                version="1.0",
                input_model=CardSuffixInput,
                output_model=CardListOutput,
                permission_level="funds_write",
                risk_level="high",
                confirmation_requirement="always",
                handler=lambda _arguments, _context: {},
            ),
            ToolSpec(
                name="card.unfreeze",
                description="Propose unfreezing an owned card.",
                version="1.0",
                input_model=CardSuffixInput,
                output_model=CardListOutput,
                permission_level="funds_write",
                risk_level="high",
                confirmation_requirement="always",
                handler=lambda _arguments, _context: {},
            ),
        )
    )

    class CompleteWithoutWriteProvider:
        mode = "openai-compatible"

        def __init__(self) -> None:
            self.available_tools: set[str] = set()

        def complete(self, messages, tools):
            del messages
            self.available_tools = {item["function"]["name"] for item in tools}
            return ModelTurn("完成了。", status="completed")

    provider = CompleteWithoutWriteProvider()
    dispatch_calls: list[str] = []
    result = AgentRuntime(provider).run(
        request_text="冻结尾号1042的卡",
        trusted_context={"task_progress": {"required_next_tools": ["card.freeze"]}},
        registry=registry,
        dispatch=lambda spec, _arguments, _call, _sequence, _error: (
            dispatch_calls.append(spec.name) or ToolDispatchResult("succeeded", {})
        ),
    )

    assert provider.available_tools == {"card__list", "card__freeze"}
    assert result.status == "failed"
    assert result.error_code == "agent_required_tool_not_called"
    assert dispatch_calls == []


def test_runtime_rejects_wrong_or_batched_write_when_a_step_is_required() -> None:
    registry = ToolRegistry(
        tuple(
            ToolSpec(
                name=name,
                description="Synthetic card operation.",
                version="1.0",
                input_model=CardSuffixInput,
                output_model=CardListOutput,
                permission_level=permission,
                risk_level="high" if permission != "read_only" else "low",
                confirmation_requirement="always" if permission != "read_only" else "never",
                handler=lambda _arguments, _context: {},
            )
            for name, permission in (
                ("card.list", "read_only"),
                ("card.freeze", "funds_write"),
                ("card.unfreeze", "funds_write"),
            )
        )
    )

    class SequenceProvider:
        mode = "openai-compatible"

        def __init__(self, calls: tuple[ModelToolCall, ...]) -> None:
            self.calls = calls

        def complete(self, messages, tools):
            del messages, tools
            return ModelTurn(None, self.calls)

    context = {"task_progress": {"required_next_tools": ["card.freeze"]}}
    dispatch_calls: list[str] = []

    def dispatch(spec, _arguments, _call, _sequence, _error):
        dispatch_calls.append(spec.name)
        return ToolDispatchResult("succeeded", {})

    wrong_write = AgentRuntime(
        SequenceProvider((ModelToolCall("wrong", "card.unfreeze", '{"card_suffix":"1042"}'),))
    ).run(
        request_text="冻结尾号1042的卡",
        trusted_context=context,
        registry=registry,
        dispatch=dispatch,
    )
    assert wrong_write.error_code == "agent_required_tool_mismatch"
    assert dispatch_calls == []

    write_batch = AgentRuntime(
        SequenceProvider(
            (
                ModelToolCall("freeze", "card.freeze", '{"card_suffix":"1042"}'),
                ModelToolCall("read", "card.list", "{}"),
            )
        )
    ).run(
        request_text="冻结尾号1042的卡",
        trusted_context=context,
        registry=registry,
        dispatch=dispatch,
    )
    assert write_batch.error_code == "agent_write_tool_batch_rejected"
    assert dispatch_calls == []


def test_runtime_hides_writes_without_request_intent_but_keeps_reads() -> None:
    registry = ToolRegistry(
        tuple(
            ToolSpec(
                name=name,
                description="Synthetic card operation.",
                version="1.0",
                input_model=CardSuffixInput,
                output_model=CardListOutput,
                permission_level=permission,
                risk_level="low",
                confirmation_requirement="never",
                handler=lambda _arguments, _context: {},
            )
            for name, permission in (("card.list", "read_only"), ("card.freeze", "funds_write"))
        )
    )

    class ObservingProvider:
        mode = "openai-compatible"

        def __init__(self) -> None:
            self.available_tools: set[str] = set()

        def complete(self, messages, tools):
            del messages
            self.available_tools = {item["function"]["name"] for item in tools}
            return ModelTurn("只读查询已结束。", status="completed")

    provider = ObservingProvider()
    result = AgentRuntime(provider).run(
        request_text="列出我的卡，不要冻结",
        trusted_context={},
        registry=registry,
        dispatch=lambda *_arguments: ToolDispatchResult("succeeded", {}),
        allowed_write_tools=frozenset(),
    )
    assert result.status == "completed"
    assert provider.available_tools == {"card__list"}


def test_openai_mode_without_settings_fails_closed_without_secret() -> None:
    selection = select_provider(Settings(_env_file=None, agent_provider="openai-compatible"))

    assert selection.provider is None
    assert selection.mode == "openai-compatible"
    assert selection.error is not None
    assert selection.error.code == "provider_not_configured"
    assert "unit-test-key" not in str(selection.error)
