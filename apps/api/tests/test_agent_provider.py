import json
from typing import Any

from finorch_api.agent.providers import OpenAICompatibleProvider, select_provider
from finorch_api.agent.runtime import FakeProvider, ToolRegistry, ToolSpec
from finorch_api.agent.tools import CardListOutput, EmptyToolInput
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
    assert definition["function"]["name"] == "card.list"
    assert definition["function"]["parameters"]["additionalProperties"] is False
    assert registry.get("card.not_registered") is None


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
    assert captured["timeout"] == 3.5
    assert provider.mode == "openai-compatible"
    assert turn.tool_calls[0].name == "card.freeze"
    assert json.loads(turn.tool_calls[0].arguments) == {"card_suffix": "1042"}


def test_openai_mode_without_settings_fails_closed_without_secret() -> None:
    selection = select_provider(Settings(agent_provider="openai-compatible"))

    assert selection.provider is None
    assert selection.mode == "openai-compatible"
    assert selection.error is not None
    assert selection.error.code == "provider_not_configured"
    assert "unit-test-key" not in str(selection.error)
