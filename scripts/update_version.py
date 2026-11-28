"""Propose the newest stable GitHub release after checking required assets."""

import argparse
import base64
import json
import os
import re
import urllib.request
from pathlib import Path
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


def open_update_pr(api: str, repository: str, branch: str, token: str) -> dict | None:
    query = urlencode(
        {
            "state": "open",
            "base": "main",
            "head": f"{repository.split('/')[0]}:{branch}",
        }
    )
    pulls = get_json(f"{api}/pulls?{query}", token)
    if not isinstance(pulls, list) or len(pulls) > 1:
        raise ValueError("Expected at most one open upgrade PR")
    if not pulls:
        return None
    pr = pulls[0]
    number, head = pr["number"], pr["head"]
    if (
        type(number) is not int
        or number <= 0
        or pr["state"] != "open"
        or pr["base"]["ref"] != "main"
        or head["ref"] != branch
        or head["repo"]["full_name"].lower() != repository.lower()
        or not re.fullmatch(r"[0-9a-f]{40}", head["sha"])
    ):
        raise ValueError("Unexpected upgrade PR identity")
    return pr


def notify_newer_release(
    api: str, number: int, current: str, version: str, homepage: str, token: str
) -> None:
    comments_url = f"{api}/issues/{number}/comments"
    marker = f"<!-- ag-cli-py-upstream-release:v{version} -->"
    page = 1
    while True:
        comments = get_json(f"{comments_url}?per_page=100&page={page}", token)
        if not isinstance(comments, list):
            raise TypeError("Expected a GitHub comment list")
        if any(
            (comment.get("user") or {}).get("login") == "github-actions[bot]"
            and marker in (comment.get("body") or "")
            for comment in comments
        ):
            return
        if len(comments) < 100:
            break
        page += 1
    body = (
        f"{marker}\n"
        f"Upstream released [AtomGit CLI v{version}]({homepage}/releases/tag/v{version}). "
        f"This PR still targets v{current}; its branch and description were left unchanged."
    )
    request = urllib.request.Request(
        comments_url,
        data=json.dumps({"body": body}).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ag-cli-py",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 201:
            raise ValueError("GitHub did not confirm creation of the release notice")


def protect_open_upgrade(
    repository: str, branch: str, version: str, homepage: str, token: str
) -> bool:
    """An open upgrade PR owns its branch and description until it is closed."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Expected a GitHub owner/repository")
    api = f"https://api.github.com/repos/{repository}"
    pr = open_update_pr(api, repository, branch, token)
    if pr is None:
        return False

    sha = pr["head"]["sha"]
    file = get_json(f"{api}/contents/wheel.json?ref={sha}", token)
    if not isinstance(file, dict) or file.get("encoding") != "base64":
        raise ValueError("Could not read wheel.json at the open upgrade PR head")
    current = stable_version(
        "v" + json.loads(base64.b64decode(file["content"]))["version"]
    )
    if canonical_version(version) > canonical_version(current):
        notify_newer_release(api, pr["number"], current, version, homepage, token)
        summary(
            f"Found upstream v{version}; kept upgrade PR #{pr['number']} at v{current}."
        )
    return True


def update_version(
    config_path: Path,
    token: str | None = None,
    report_path: Path | None = None,
    *,
    packaging_repository: str | None = None,
    pr_branch: str | None = None,
) -> bool:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    repository = upstream_repository(config["homepage"])
    release = latest_release(repository, token)
    previous = config["version"]
    version = stable_version(release["tag_name"])
    if canonical_version(version) <= canonical_version(previous):
        outputs(changed="false", version=previous)
        return False
    if packaging_repository is not None or pr_branch is not None:
        if not (packaging_repository and pr_branch and token):
            raise ValueError(
                "Upgrade PR protection requires repository, branch and token"
            )
        if protect_open_upgrade(
            packaging_repository, pr_branch, version, config["homepage"], token
        ):
            outputs(changed="false", version=previous)
            return False
    version = candidate_release(config, release)
    assert version is not None
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
    outputs(changed="true", previous_version=previous, version=version)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--packaging-repository")
    parser.add_argument("--pr-branch")
    args = parser.parse_args()
    update_version(
        ROOT / "wheel.json",
        os.environ.get("GITHUB_TOKEN"),
        args.report,
        packaging_repository=args.packaging_repository,
        pr_branch=args.pr_branch,
    )


if __name__ == "__main__":
    main()
