"""Common LLM provider interface.

Every adapter implements `LLMProvider` so the router can treat them
identically. Adapters are intentionally thin: credential handling, a
single `chat()` call, a `check_credit()` call (may return None when the
provider has no programmatic credit endpoint), and a name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CreditStatus:
    """Estimated remaining credit for a provider.

    `has_endpoint` is True when the value comes from a real usage/billing
    endpoint; False when it's a rolling local estimate. `remaining` is a
    fraction in [0, 1] of the monthly free tier, or None when unknown.
    """

    remaining: float | None = None
    has_endpoint: bool = False
    detail: str = ""


@dataclass
class ProviderResult:
    """Result of a chat() call."""

    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(ABC):
    """Interface implemented by every provider adapter."""

    #: Stable identifier used in the GUI/logs (e.g. "groq").
    name: str = "base"
    #: Human-friendly label.
    label: str = "Base Provider"
    #: Provider is local and infinite (Ollama).
    is_local: bool = False
    #: Whether a real credit endpoint exists.
    has_credit_endpoint: bool = False

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or ""
        self.model = model or ""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        """Send a chat completion. Raises ProviderError on failure."""

    @abstractmethod
    def check_credit(self) -> CreditStatus:
        """Return remaining credit estimate or None-when-unknown fields."""

    def available(self) -> bool:
        """Whether this provider can be used right now."""
        return True


class ProviderError(Exception):
    """Raised when a provider call fails (auth, quota, network, etc.)."""

    def __init__(self, message: str, retryable: bool = True, code: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code
