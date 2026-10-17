"""Shared version parsing and GitHub Actions reporting."""

import os
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def canonical_version(value: str) -> Version:
    """Require canonical spelling so package versions preserve upstream names."""
    version = Version(value)
    if str(version) != value:
        raise ValueError(f"Expected a canonical PEP 440 version, got {value!r}")
    return version


def outputs(**values: str) -> None:
    """Print single-line values and append them to GITHUB_OUTPUT when set."""
    text = "".join(f"{key}={value}\n" for key, value in values.items())
    print(text, end="")
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(text)


def summary(text: str) -> None:
    """Print Markdown and append it to GITHUB_STEP_SUMMARY when set."""
    print(text)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")
