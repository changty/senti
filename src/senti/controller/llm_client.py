"""Async LLM wrapper using LiteLLM with multi-provider support."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

import litellm
import yaml

from senti.config import Settings
from senti.exceptions import LLMError

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


@dataclass
class ModelConfig:
    """A predefined model entry from models.yaml."""

    name: str
    model: str  # LiteLLM model string
    provider: str  # ollama, openai, gemini, anthropic
    description: str = ""


class LLMClient:
    """Async LLM wrapper with runtime model switching."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models: dict[str, ModelConfig] = {}
        self._active: ModelConfig | None = None
        self._load_models()
        self._setup_api_keys()

    def _load_models(self) -> None:
        """Load predefined models from config/models.yaml."""
        path = self._settings.models_config_path
        if not path.exists():
            # Fallback: single model from .env
            self._models["default"] = ModelConfig(
                name="default",
                model=self._settings.llm_model,
                provider="ollama",
                description="Default model from .env",
            )
            self._active = self._models["default"]
            return

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for name, cfg in raw.get("models", {}).items():
            self._models[name] = ModelConfig(
                name=name,
                model=cfg["model"],
                provider=cfg.get("provider", "ollama"),
                description=cfg.get("description", ""),
            )

        default_name = raw.get("default", "")
        if default_name and default_name in self._models:
            self._active = self._models[default_name]
        elif self._models:
            self._active = next(iter(self._models.values()))

        logger.info(
            "Loaded %d models, active: %s",
            len(self._models),
            self._active.name if self._active else "none",
        )

    def _setup_api_keys(self) -> None:
        """Set API keys as environment variables for LiteLLM."""
        s = self._settings
        if s.openai_api_key:
            os.environ["OPENAI_API_KEY"] = s.openai_api_key
        if s.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = s.gemini_api_key
        if s.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = s.anthropic_api_key

    @property
    def active_model(self) -> ModelConfig | None:
        return self._active

    @property
    def available_models(self) -> dict[str, ModelConfig]:
        return self._models

    def switch_model(self, name: str) -> ModelConfig:
        """Switch to a predefined model by name. Raises LLMError if not found."""
        if name not in self._models:
            available = ", ".join(self._models.keys())
            raise LLMError(f"Unknown model '{name}'. Available: {available}")

        self._active = self._models[name]
        logger.info("Switched to model: %s (%s)", name, self._active.model)
        return self._active

    def _build_kwargs(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        """Build the kwargs dict for litellm.acompletion()."""
        if not self._active:
            raise LLMError("No active model configured.")

        kwargs: dict[str, Any] = {
            "model": self._active.model,
            "messages": messages,
        }

        # Ollama needs api_base
        if self._active.provider == "ollama":
            kwargs["api_base"] = self._settings.ollama_host

        if tools:
            kwargs["tools"] = tools

        return kwargs

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Check if an exception is transient and worth retrying."""
        exc_str = str(exc).lower()
        # Non-retryable: auth and invalid model errors
        for code in ("401", "403", "404"):
            if code in exc_str:
                return False
        if "authentication" in exc_str or "unauthorized" in exc_str:
            return False
        # Retryable: timeouts, connection errors, rate limits, server errors
        for indicator in ("timeout", "connection", "429", "500", "502", "503",
                          "rate limit", "overloaded", "service unavailable"):
            if indicator in exc_str:
                return True
        # Retryable by exception type
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return True
        return False

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request with retry, returning the response message dict."""
        kwargs = self._build_kwargs(messages, tools)
        max_retries = self._settings.llm_max_retries
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                response = await litellm.acompletion(**kwargs)
            except Exception as exc:
                last_exc = exc
                model_name = self._active.name if self._active else "?"
                if attempt < max_retries - 1 and self._is_retryable(exc):
                    delay = min(2 ** attempt, 30)
                    logger.warning(
                        "LLM call failed (%s), attempt %d/%d, retrying in %ds: %s",
                        model_name, attempt + 1, max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("LLM call failed (%s): %s", model_name, exc)
                raise LLMError(f"LLM completion failed: {exc}") from exc
            else:
                break
        else:
            # All retries exhausted
            model_name = self._active.name if self._active else "?"
            logger.error("LLM call failed after %d attempts (%s): %s", max_retries, model_name, last_exc)
            raise LLMError(f"LLM completion failed after {max_retries} attempts: {last_exc}") from last_exc

        message = response.choices[0].message
        result: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }

        # Extract usage data if available
        usage = getattr(response, "usage", None)
        if usage:
            result["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                "model": self._active.name if self._active else "unknown",
            }
        else:
            result["usage"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "model": self._active.name if self._active else "unknown",
            }

        # Native tool_calls
        if hasattr(message, "tool_calls") and message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for i, tc in enumerate(message.tool_calls)
            ]
            return result

        # Fallback: try to parse tool calls from content
        if tools and message.content:
            parsed = self._try_parse_tool_calls(message.content)
            if parsed:
                result["tool_calls"] = parsed
                result["content"] = ""

        return result

    @staticmethod
    def _try_parse_tool_calls(content: str) -> list[dict[str, Any]] | None:
        """Attempt to extract tool calls from JSON in the response content."""
        patterns = [
            re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL),
            re.compile(r"```\s*(\{.*?\})\s*```", re.DOTALL),
        ]
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if "name" in data and "arguments" in data:
                        return [
                            {
                                "id": "call_parsed_0",
                                "type": "function",
                                "function": {
                                    "name": data["name"],
                                    "arguments": (
                                        json.dumps(data["arguments"])
                                        if isinstance(data["arguments"], dict)
                                        else str(data["arguments"])
                                    ),
                                },
                            }
                        ]
                except (json.JSONDecodeError, KeyError):
                    continue
        return None
