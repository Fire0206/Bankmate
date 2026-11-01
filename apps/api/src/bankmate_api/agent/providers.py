import ipaddress
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr

from bankmate_api.agent.runtime import (
    AgentProviderError,
    LLMProvider,
    ModelToolCall,
    ModelTurn,
    RuleProvider,
)
from bankmate_api.config import Settings


@dataclass(frozen=True)
class ProviderSelection:
    provider: LLMProvider | None
    mode: str
    error: AgentProviderError | None = None


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _open_provider_request(request: urllib.request.Request, *, timeout: float) -> Any:
    opener = urllib.request.build_opener(_RejectRedirects())
    return opener.open(request, timeout=timeout)


def _provider_url_error(base_url: str) -> str | None:
    if base_url != base_url.strip() or any(character.isspace() for character in base_url):
        return "The configured provider URL contains invalid whitespace."
    try:
        parsed = urlparse(base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return "The configured provider URL is invalid."
    if parsed.scheme not in {"http", "https"} or not hostname:
        return "The configured provider URL must be an absolute HTTP or HTTPS URL."
    if parsed.username is not None or parsed.password is not None:
        return "Credentials must not be embedded in the configured provider URL."
    if parsed.query or parsed.fragment:
        return "The configured provider URL must not contain a query or fragment."
    if parsed.scheme == "http":
        normalized_host = hostname.rstrip(".").lower()
        try:
            loopback = ipaddress.ip_address(normalized_host).is_loopback
        except ValueError:
            loopback = normalized_host == "localhost"
        if not loopback:
            return "Non-local model provider URLs must use HTTPS."
    return None


def select_provider(settings: Settings) -> ProviderSelection:
    # Keep accepting `fake` for existing local .env files; `rules` is the current name.
    if settings.agent_provider in {"rules", "fake"}:
        return ProviderSelection(
            provider=RuleProvider(),
            mode=settings.agent_provider,
        )
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        return ProviderSelection(
            provider=None,
            mode="openai-compatible",
            error=AgentProviderError(
                "provider_not_configured",
                "OpenAI-compatible mode requires a base URL, API key, and model name.",
            ),
        )
    if not settings.llm_data_egress_enabled:
        return ProviderSelection(
            provider=None,
            mode="openai-compatible",
            error=AgentProviderError(
                "provider_not_configured",
                "External model requests are disabled. Explicitly enable model data egress "
                "only when using synthetic data and a trusted provider.",
            ),
        )
    url_error = _provider_url_error(settings.llm_base_url)
    if url_error:
        return ProviderSelection(
            provider=None,
            mode="openai-compatible",
            error=AgentProviderError("provider_not_configured", url_error),
        )
    return ProviderSelection(
        provider=OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
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
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.get_secret_value()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        return self._complete(messages, tools, tool_choice="auto")

    def complete_required_tool(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str,
    ) -> ModelTurn:
        provider_name = tool_name.replace(".", "__")
        if not any(
            item.get("function", {}).get("name") == provider_name
            for item in tools
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        ):
            raise AgentProviderError(
                "agent_required_tool_unavailable",
                "A required workflow tool is not available to the configured provider.",
            )
        return self._complete(
            messages,
            tools,
            tool_choice={"type": "function", "function": {"name": provider_name}},
        )

    def _complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str | dict[str, Any],
    ) -> ModelTurn:
        endpoint = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": self.temperature,
        }
        # DeepSeek's reasoning mode uses a separate reasoning_content field in
        # multi-turn tool calls. The current common adapter intentionally does
        # not persist or replay that field, so disable reasoning for tool turns.
        if urlparse(self.base_url).hostname == "api.deepseek.com":
            request_body["thinking"] = {"type": "disabled"}
        body = json.dumps(request_body).encode("utf-8")
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
            with _open_provider_request(request, timeout=self.timeout_seconds) as response:
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
            choices = payload["choices"]
            if not isinstance(choices, list) or not choices:
                raise ValueError("The provider returned no choices.")
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise ValueError("The provider returned an invalid message.")
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError("The provider returned invalid message content.")
            raw_calls = message.get("tool_calls") or []
            if not isinstance(raw_calls, list):
                raise ValueError("The provider returned invalid tool calls.")
            calls_list: list[ModelToolCall] = []
            call_ids: set[str] = set()
            for item in raw_calls:
                if not isinstance(item, dict) or item.get("type", "function") != "function":
                    raise ValueError("The provider returned an unsupported tool call.")
                call_id = item.get("id")
                function = item.get("function")
                if not isinstance(call_id, str) or not call_id.strip() or call_id in call_ids:
                    raise ValueError("The provider returned a missing or duplicate tool call ID.")
                if not isinstance(function, dict):
                    raise ValueError("The provider returned an invalid tool function.")
                name = function.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("The provider returned an invalid tool name.")
                arguments = function.get("arguments")
                encoded_arguments = (
                    arguments if isinstance(arguments, str) else json.dumps(arguments)
                )
                call_ids.add(call_id)
                calls_list.append(ModelToolCall(id=call_id, name=name, arguments=encoded_arguments))
            calls = tuple(calls_list)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AgentProviderError(
                "llm_provider_invalid_response",
                "The configured model provider returned an invalid turn.",
            ) from exc

        return ModelTurn(content=str(content) if content is not None else None, tool_calls=calls)
