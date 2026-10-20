import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

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
            temperature=settings.llm_temperature,
            usage_file=(settings.eval_usage_file if settings.environment == "test" else None),
            max_tokens=(
                settings.eval_max_completion_tokens if settings.environment == "test" else None
            ),
            hard_budget_cny=(
                settings.eval_hard_budget_cny if settings.environment == "test" else None
            ),
            initial_cost_cny=(
                settings.eval_initial_cost_cny if settings.environment == "test" else 0.0
            ),
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
        usage_file: Path | None = None,
        max_tokens: int | None = None,
        hard_budget_cny: float | None = None,
        initial_cost_cny: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.get_secret_value()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.usage_file = usage_file
        self.max_tokens = max_tokens
        self.hard_budget_cny = hard_budget_cny
        self.initial_cost_cny = initial_cost_cny
        self._usage_lock = threading.Lock()

    def _record_event(self, event: dict[str, Any]) -> None:
        """Append sanitized evaluation telemetry; never persist request content."""
        if self.usage_file is None:
            return
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        with self._usage_lock, self.usage_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")

    def _record_usage(self, call_id: str, usage: Any) -> None:
        """Append provider token counts only; never persist prompts or responses."""
        event: dict[str, Any] = {
            "event": "response_usage",
            "call_id": call_id,
            "model": self.model,
            "usage_available": False,
        }
        if isinstance(usage, dict):
            counts: dict[str, int] = {}
            for source, target in (
                ("prompt_tokens", "prompt_tokens"),
                ("completion_tokens", "completion_tokens"),
                ("total_tokens", "total_tokens"),
                ("prompt_cache_hit_tokens", "cached_prompt_tokens"),
            ):
                value = usage.get(source)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    counts[target] = value
            if counts:
                event.update(counts)
                event["usage_available"] = True
        self._record_event(event)

    def _enforce_evaluation_budget(self) -> None:
        if self.usage_file is None or self.max_tokens is None or self.hard_budget_cny is None:
            return

        started: set[str] = set()
        responded: set[str] = set()
        cost_cny = self.initial_cost_cny
        with self._usage_lock:
            if self.usage_file.exists():
                usage_lines = self.usage_file.read_text(encoding="utf-8").splitlines()
            else:
                usage_lines = []
            for line in usage_lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    raise AgentProviderError(
                        "evaluation_usage_invalid", "Evaluation usage telemetry is invalid."
                    ) from None
                if event.get("event") == "request_started":
                    started.add(event.get("call_id"))
                elif event.get("event") == "response_usage":
                    call_id = event.get("call_id")
                    responded.add(call_id)
                    if not event.get("usage_available"):
                        raise AgentProviderError(
                            "evaluation_usage_unavailable",
                            "Evaluation stopped because a provider call had no token usage.",
                        )
                    prompt_tokens = event.get("prompt_tokens")
                    completion_tokens = event.get("completion_tokens")
                    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
                        raise AgentProviderError(
                            "evaluation_usage_incomplete",
                            "Evaluation stopped because provider token usage was incomplete.",
                        )
                    cost_cny += (prompt_tokens * 0.30 + completion_tokens * 1.20) / 1_000_000 * 10.0

        if started - responded:
            raise AgentProviderError(
                "evaluation_usage_unavailable",
                "Evaluation stopped because a provider request has unaccounted usage.",
            )

        next_request_reserve_cny = (1_000_000 * 0.30 + self.max_tokens * 1.20) / 1_000_000 * 10.0
        if cost_cny + next_request_reserve_cny > self.hard_budget_cny:
            raise AgentProviderError(
                "evaluation_budget_limit",
                "The Phase 2D hard model evaluation budget has been reached.",
            )

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        endpoint = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            request_body["max_tokens"] = self.max_tokens
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
        self._enforce_evaluation_budget()
        call_id = uuid4().hex
        self._record_event({"event": "request_started", "call_id": call_id, "model": self.model})
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

        self._record_usage(call_id, payload.get("usage") if isinstance(payload, dict) else None)

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
