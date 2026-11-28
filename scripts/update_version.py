"""Propose the newest stable GitHub release after checking required assets."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit

from scripts.common import ROOT, canonical_version, outputs, summary
from scripts.upstream import asset_names, get_json, stable_version, upstream_repository


def latest_release(repository: str, token: str | None = None) -> dict:
    """Select the highest stable version across all GitHub release pages."""
    releases = []
    seen = set()
    page = 1
    while True:
        batch = get_json(
            f"https://api.github.com/repos/{repository}/releases"
            f"?page={page}&per_page=100",
            token,
        )
        if not isinstance(batch, list):
            raise TypeError("Expected a GitHub release array")
        for release in batch:
            tag = release["tag_name"]
            if tag in seen:
                raise ValueError(f"Repeated release while paginating: {tag}")
            seen.add(tag)
            if release.get("draft") or release.get("prerelease"):
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
        raise ValueError("No stable GitHub release found")
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


def update_already_exists(repository: str, branch: str, token: str) -> bool:
    """Do not reuse a version branch or recreate a closed version PR."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Expected a GitHub owner/repository")
    api = f"https://api.github.com/repos/{repository}"
    owner = repository.split("/")[0]
    query = urlencode({"state": "all", "base": "main", "head": f"{owner}:{branch}"})
    pulls = get_json(f"{api}/pulls?{query}", token)
    if not isinstance(pulls, list):
        raise TypeError("Expected a GitHub pull request list")
    if pulls:
        return True

    try:
        ref = get_json(f"{api}/git/ref/heads/{branch}", token)
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    if not isinstance(ref, dict) or ref.get("ref") != f"refs/heads/{branch}":
        raise ValueError("Unexpected version branch identity")
    return True


def update_version(
    config_path: Path,
    token: str | None = None,
    report_path: Path | None = None,
    *,
    packaging_repository: str | None = None,
) -> bool:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    repository = upstream_repository(config["homepage"])
    release = latest_release(repository, token)
    version = candidate_release(config, release)
    previous = config["version"]
    if version is None:
        outputs(changed="false", version=previous)
        return False
    branch = f"update/atomgit-v{version}"
    if packaging_repository is not None:
        if not token:
            raise ValueError("Checking existing upgrades requires a GitHub token")
        if update_already_exists(packaging_repository, branch, token):
            summary(f"Upgrade v{version} already exists; left it unchanged.")
            outputs(changed="false", version=previous)
            return False
    if report_path:
        report_path.write_text(
            f"Update AtomGit CLI from {previous} to {version}.\n\n"
            f"Upstream release: {config['homepage']}/releases/tag/v{version}\n\n"
            "All configured archives and checksums.txt have unique HTTPS asset "
            "links. CI will download, verify SHA-256 checksums, build and test "
            "the wheels.\n\n"
            "For agent-assisted validation, use `$atomgit-release-upgrade` "
            "(`.agents/skills/atomgit-release-upgrade/SKILL.md`).\n",
            encoding="utf-8",
        )
    config["version"] = version
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    outputs(changed="true", previous_version=previous, version=version, branch=branch)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--packaging-repository")
    args = parser.parse_args()
    update_version(
        ROOT / "wheel.json",
        os.environ.get("GITHUB_TOKEN"),
        args.report,
        packaging_repository=args.packaging_repository,
    )


if __name__ == "__main__":
    main()
