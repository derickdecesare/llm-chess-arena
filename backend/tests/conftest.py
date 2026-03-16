"""Shared fixtures for backend tests."""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
