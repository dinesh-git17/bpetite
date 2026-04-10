"""Smoke tests for the installed bpetite package."""

import bpetite


def test_package_importable() -> None:
    """The bpetite package resolves from the installed environment."""
    assert bpetite.__name__ == "bpetite"
