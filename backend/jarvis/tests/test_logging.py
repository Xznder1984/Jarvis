"""Tests for the unified log broker, redaction, resampling, and settings."""
import logging

import numpy as np

from jarvis.logging_setup import RedactingFormatter, redact
from jarvis.logs import LogBridgeHandler, broker


def test_redact_key_patterns():
    cases = {
        "api key=sk-abcdefghijklmnop123": "api key=sk-***",
        "sk-abcdefghijklmnop": "sk-***",
        "csk-123456789012": "csk-***",
        "Bearer abcdef1234567890abcdef": "Bearer <redacted>",
        "NVIDIA_API_KEY=nv-xyz1234567890": "NVIDIA_API_KEY=<redacted>",
        "plain text, no secrets here": "plain text, no secrets here",
    }
    for raw, expected in cases.items():
        assert redact(raw) == expected, (raw, redact(raw))


def test_formatter_redacts_records():
    fmt = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "key=sk-abcdefghijklmnop123", (), None
    )
    out = fmt.format(record)
    assert "sk-abcdefghijklmnop123" not in out
    assert "sk-***" in out


def test_broker_ring_and_levels():
    broker.clear()
    broker.publish("info", "hello", source="backend")
    broker.publish("warn", "careful", source="shell")
    broker.publish("warning", "mapped-to-warn", source="frontend")
    items = broker.recent(10)
    assert items[0]["message"] == "mapped-to-warn"
    assert items[0]["level"] == "warn"
    assert items[1]["level"] == "warn"
    assert items[2]["level"] == "info"
    assert {i["source"] for i in items} == {"backend", "shell", "frontend"}


def test_broker_redacts_published_messages():
    broker.clear()
    broker.publish("info", "token=sk-supersecret", source="shell")
    items = broker.recent(1)
    assert "sk-supersecret" not in items[0]["message"]


def test_log_bridge_handler():
    broker.clear()
    handler = LogBridgeHandler(broker)
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "bridge test", (), None)
    handler.emit(record)
    items = broker.recent(1)
    assert items[0]["message"] == "bridge test"
    assert items[0]["level"] == "warn"
    assert items[0]["source"] == "backend"


def test_resample_to_16k():
    from jarvis.stt.whisper import resample_to_16k

    # 48 kHz, one second -> 16000 samples.
    x = np.sin(np.linspace(0, 200, 48000)).astype(np.float32)
    y = resample_to_16k(x, 48000)
    assert len(y) == 16000
    # Same-rate is a no-op (returns the input array unchanged).
    assert resample_to_16k(x, 16000) is x
    # Tiny input is returned untouched.
    tiny = x[:1]
    assert resample_to_16k(tiny, 48000) is tiny


def test_priority_coercion():
    from jarvis.config import Config

    c = Config()
    assert c._coerce_priority(["a", "b"]) == ["a", "b"]
    assert c._coerce_priority('["a", "b"]') == ["a", "b"]
    assert c._coerce_priority("not json") is None
    assert c._coerce_priority({"x": 1}) is None


def test_masked_settings_hides_key_values():
    from jarvis.config import Config

    c = Config()
    masked = c.masked_settings()
    # No API key value should ever leak; keys become True flags.
    for key, value in masked.items():
        if key.endswith("_API_KEY") and value:
            assert value is True
