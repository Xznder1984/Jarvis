"""Tests for the health endpoints."""
from __future__ import annotations

import time
from fastapi.testclient import TestClient

from jarvis.main import app


def test_health_basic():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["service"] == "jarvis-backend"


def test_health_detailed_structure():
    client = TestClient(app)
    resp = client.get("/api/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    # Required top-level keys
    assert data["ok"] is True
    assert data["service"] == "jarvis-backend"
    assert "version" in data
    assert "uptime_seconds" in data
    assert "uptime_human" in data
    assert "process" in data
    assert "websocket" in data
    assert "stt" in data
    assert "tts" in data
    assert "llm" in data

    # Process metrics
    proc = data["process"]
    assert "pid" in proc
    assert "rss_mb" in proc
    assert "vms_mb" in proc
    assert "cpu_percent" in proc
    assert "threads" in proc
    assert isinstance(proc["rss_mb"], (int, float))
    assert proc["rss_mb"] > 0

    # WebSocket clients
    ws = data["websocket"]
    assert "connected_clients" in ws
    assert isinstance(ws["connected_clients"], int)

    # STT info
    stt = data["stt"]
    assert "model" in stt
    assert "compute_type" in stt
    assert "model_loaded" in stt
    assert isinstance(stt["model_loaded"], bool)

    # TTS/LLM info
    assert "active_provider" in data["tts"]
    assert "provider_priority" in data["llm"]
    assert "active_provider" in data["llm"]


def test_health_detailed_uptime_increases():
    client = TestClient(app)
    r1 = client.get("/api/health/detailed")
    t1 = r1.json()["uptime_seconds"]
    time.sleep(0.05)
    r2 = client.get("/api/health/detailed")
    t2 = r2.json()["uptime_seconds"]
    assert t2 >= t1