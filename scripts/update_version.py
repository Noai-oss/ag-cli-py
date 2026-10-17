"""Propose the newest stable AtomGit release after checking required assets."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from scripts.common import ROOT, canonical_version, outputs
from scripts.upstream import asset_names, get_json, stable_version, upstream_repository


def latest_release(repository: str, token: str | None = None) -> dict:
    """Read AtomGit's paginated list; it has no GitHub /releases/latest contract."""
    releases = []
    seen = set()
    page = 1
    while True:
        batch = get_json(
            f"https://api.atomgit.com/api/v5/repos/{repository}/releases"
            f"?page={page}&per_page=100&direction=desc",
            token,
        )
        if not isinstance(batch, list):
            raise TypeError("Expected an AtomGit release array")
        for release in batch:
            tag = release["tag_name"]
            if tag in seen:
                raise ValueError(f"Repeated release while paginating: {tag}")
            seen.add(tag)
            if (
                release.get("draft")
                or release.get("prerelease")
                or release.get("release_status") == "pre"
            ):
                continue
            try:
                version = stable_version(tag)
            except ValueError:
                continue
            releases.append((canonical_version(version), release))
        if len(batch) < 100:
            break
        page += 1
    if not releases:
        raise ValueError("No stable AtomGit release found")
    return max(releases, key=lambda item: item[0])[1]


def candidate_release(config: dict, release: dict) -> str | None:
    version = stable_version(release["tag_name"])
    if canonical_version(version) <= canonical_version(config["version"]):
        return None
    for name in asset_names(config):
        matches = [asset for asset in release["assets"] if asset["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one upstream asset: {name}")
        url = urlsplit(matches[0]["browser_download_url"])
        if url.scheme != "https" or not url.netloc:
            raise ValueError(f"Expected an HTTPS download URL for {name}")
    return version


def update_version(
    config_path: Path, token: str | None = None, report_path: Path | None = None
) -> bool:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    repository = upstream_repository(config["homepage"])
    release = latest_release(repository, token)
    version = candidate_release(config, release)
    previous = config["version"]
    if version is None:
        outputs(changed="false", version=previous)
        return False
    if report_path:
        report_path.write_text(
            f"Update AtomGit CLI from {previous} to {version}.\n\n"
            f"Upstream release: {config['homepage']}/releases/v{version}\n\n"
            "All configured archives and checksums.txt have unique HTTPS asset "
            "links. CI will download, verify SHA-256 checksums, build and test "
            "the wheels.\n\n"
            "Review platform compatibility and this PR, then publish "
            f"tag v{version} from main.\n",
            encoding="utf-8",
        )
    config["version"] = version
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    outputs(changed="true", previous_version=previous, version=version)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    update_version(ROOT / "wheel.json", os.environ.get("ATOMGIT_TOKEN"), args.report)


if __name__ == "__main__":
    main()
