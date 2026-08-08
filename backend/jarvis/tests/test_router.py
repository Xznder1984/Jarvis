"""Provider router tests using fake providers (no live API calls)."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from jarvis.providers.base import CreditStatus, LLMProvider, ProviderError, ProviderResult


@dataclass
class FakeConfig:
    api_keys: dict = None
    credit_low_threshold: float = 0.10

    def __post_init__(self):
        if self.api_keys is None:
            self.api_keys = {}

    def get(self, key, default=None):
        return self.api_keys.get(key, default)


class FakeProvider(LLMProvider):
    def __init__(self, name, *, fail=False, low=False, local=False, available=True, has_endpoint=False):
        self.name = name
        self.label = name.title()
        self.is_local = local
        self.has_credit_endpoint = has_endpoint
        self.api_key = "test-key"
        self.model = "test-model"
        self._fail = fail
        self._low = low
        self._available = available

    def chat(self, messages, **kwargs):
        if self._fail:
            raise ProviderError(f"{self.label} failed", code="quota")
        return ProviderResult(text=f"reply-from-{self.name}", provider=self.name, model=self.model)

    def check_credit(self):
        return CreditStatus(remaining=0.05 if self._low else 0.9, has_endpoint=False)

    def available(self):
        return self._available


def _make_router(providers, priority, config=None):
    """Build a ProviderRouter instance with injected fakes."""
    import jarvis.router as r

    router = object.__new__(r.ProviderRouter)
    router._config = config or FakeConfig()
    router._lock = threading.Lock()
    router._usage = {}
    router._on_notify = None
    router._on_provider_update = None
    router.providers = providers
    router.priority = priority
    router.active_provider = None
    return router


def test_failover_to_next_provider():
    providers = {"primary": FakeProvider("primary", fail=True), "backup": FakeProvider("backup")}
    router = _make_router(providers, ["primary", "backup"])
    text, provider = router.chat([{"role": "user", "content": "hi"}])
    assert provider == "backup"
    assert text == "reply-from-backup"


def test_low_credit_skips_provider():
    providers = {
        "primary": FakeProvider("primary", low=True, has_endpoint=True),
        "backup": FakeProvider("backup"),
    }
    router = _make_router(providers, ["primary", "backup"])
    text, provider = router.chat([{"role": "user", "content": "hi"}])
    assert provider == "backup"
    assert text == "reply-from-backup"


def test_local_ollama_last_resort():
    providers = {
        "primary": FakeProvider("primary", fail=True),
        "ollama": FakeProvider("ollama", local=True),
    }
    router = _make_router(providers, ["primary"])
    text, provider = router.chat([{"role": "user", "content": "hi"}])
    assert provider == "ollama"
    assert text == "reply-from-ollama"


def test_all_exhausted_raises():
    providers = {"primary": FakeProvider("primary", fail=True)}
    router = _make_router(providers, ["primary"])
    try:
        router.chat([{"role": "user", "content": "hi"}])
        assert False, "expected ProviderError"
    except ProviderError:
        pass


def test_credit_estimate_local():
    import jarvis.router as r

    providers = {"cerebras": FakeProvider("cerebras")}
    router = _make_router(providers, ["cerebras"])
    r.FREE_TIER_BUDGETS["cerebras"] = 100
    router._usage["cerebras"] = {"prompt": 50, "completion": 0}
    status = router.credit_for("cerebras")
    assert status.remaining is not None
    assert status.remaining < 1.0
    assert status.has_endpoint is False
