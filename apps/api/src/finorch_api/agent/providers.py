import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from finorch_api.agent.runtime import (
    AgentProviderError,
    FakeProvider,
    LLMProvider,
    ModelToolCall,
    ModelTurn,
)
from finorch_api.config import Settings


@dataclass(frozen=True)
class ProviderSelection:
    provider: LLMProvider | None
    mode: str
    error: AgentProviderError | None = None


def select_provider(settings: Settings) -> ProviderSelection:
    if settings.agent_provider == "fake":
        return ProviderSelection(provider=FakeProvider(), mode="fake")
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        return ProviderSelection(
            provider=None,
            mode="openai-compatible",
            error=AgentProviderError(
                "provider_not_configured",
                "OpenAI-compatible mode requires a base URL, API key, and model name.",
            ),
        )
    if not settings.llm_base_url.startswith(("http://", "https://")):
        return ProviderSelection(
            provider=None,
            mode="openai-compatible",
            error=AgentProviderError(
                "provider_not_configured", "The configured provider URL must use HTTP or HTTPS."
            ),
        )
    return ProviderSelection(
        provider=OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        mode="openai-compatible",
    )


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible Chat Completions adapter using configured server credentials."""

    mode = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.get_secret_value()
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        endpoint = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        body = json.dumps(
            {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise AgentProviderError(
                "llm_provider_http_error", "The configured model provider returned an error."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AgentProviderError(
                "llm_provider_unavailable", "The configured model provider could not be reached."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AgentProviderError(
                "llm_provider_invalid_response",
                "The configured model provider returned invalid JSON.",
            ) from exc

        try:
            message = payload["choices"][0]["message"]
            content = message.get("content")
            calls = tuple(
                ModelToolCall(
                    id=str(item["id"]),
                    name=str(item["function"]["name"]),
                    arguments=(
                        item["function"]["arguments"]
                        if isinstance(item["function"]["arguments"], str)
                        else json.dumps(item["function"]["arguments"])
                    ),
                )
                for item in message.get("tool_calls", [])
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentProviderError(
                "llm_provider_invalid_response",
                "The configured model provider returned an invalid turn.",
            ) from exc

        return ModelTurn(content=str(content) if content is not None else None, tool_calls=calls)
