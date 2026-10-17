"""AtomGit release naming and public API access."""

import json
import re
import urllib.request
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from scripts.common import canonical_version

COMMAND = "ag-cli"


def archive_name(target: str) -> str:
    """Release archives retain the ag_ prefix after the command rename."""
    suffix = ".zip" if target.startswith("windows_") else ".tar.gz"
    return f"ag_{target}{suffix}"


def asset_names(config: dict) -> list[str]:
    targets = {
        PurePosixPath(entries[0]["path"]).parent.name
        for entries in config["binaries"].values()
    }
    return [archive_name(target) for target in sorted(targets)] + ["checksums.txt"]


def upstream_repository(homepage: str) -> str:
    url = urlsplit(homepage)
    repository = url.path.strip("/")
    if (
        url.scheme != "https"
        or url.netloc not in ("atomgit.com", "gitcode.com")
        or url.query
        or url.fragment
        or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository)
    ):
        raise ValueError(f"Expected an AtomGit repository homepage, got {homepage!r}")
    return repository


def stable_version(tag: str) -> str:
    """Keep the upstream three-component stable tag spelling."""
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"Expected a stable upstream vX.Y.Z tag, got {tag!r}")
    canonical_version(tag[1:])
    return tag[1:]


def fetch(url: str) -> bytes:
    """Download public release bytes without forwarding API credentials."""
    request = urllib.request.Request(url, headers={"User-Agent": "ag-cli-py"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def get_json(url: str, token: str | None = None) -> list | dict:
    headers = {"User-Agent": "ag-cli-py", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, (list, dict)):
        raise TypeError(f"Expected a JSON array or object from {url}")
    return value
