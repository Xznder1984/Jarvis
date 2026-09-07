"""Pytest configuration and fixtures for JARVIS backend tests."""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live-backend", action="store_true", help="run tests against live backend at ws://127.0.0.1:8765/ws"
    )


@pytest.fixture
def live_backend(request):
    """True if --live-backend flag was passed."""
    return request.config.getoption("--live-backend")