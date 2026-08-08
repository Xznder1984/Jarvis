"""Contract envelope tests."""
from jarvis.contract import build, parse


def test_build_envelope():
    env = build("say", {"text": "hello"})
    assert env["type"] == "say"
    assert env["payload"] == {"text": "hello"}
    assert env["id"]
    assert env["ts"] > 0


def test_parse_roundtrip():
    env = build("state_update", {"state": "thinking"})
    import json

    parsed = parse(json.dumps(env))
    assert parsed["type"] == "state_update"
    assert parsed["payload"]["state"] == "thinking"


def test_parse_garbage():
    assert parse("not json") == {}
    assert parse('{"hello": 1}') == {}
