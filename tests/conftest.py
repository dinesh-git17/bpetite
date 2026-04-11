"""Shared pytest fixtures for the bpetite test suite."""

from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def tiny_corpus() -> str:
    """Return the deterministic training corpus from ``tests/fixtures/tiny.txt``."""
    return (_FIXTURES_DIR / "tiny.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def unicode_corpus() -> str:
    """Return the multi-script Unicode corpus from ``tests/fixtures/unicode.txt``."""
    return (_FIXTURES_DIR / "unicode.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def empty_corpus() -> str:
    """Return the empty corpus from ``tests/fixtures/empty.txt``."""
    return (_FIXTURES_DIR / "empty.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def invalid_utf8_path() -> Path:
    """Return the filesystem path to ``tests/fixtures/invalid_utf8.bin``."""
    return _FIXTURES_DIR / "invalid_utf8.bin"
