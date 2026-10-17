"""Resolve a version tag and check whether it may be published."""

import argparse
import json
import subprocess
from pathlib import Path

from scripts.common import ROOT, canonical_version, outputs, summary


def validate_ref(config: dict, ref: str) -> None:
    """Require a canonical config version and its exact refs/tags/v<version>."""
    canonical_version(config["version"])
    if ref != f"refs/tags/v{config['version']}":
        raise ValueError(f"Expected refs/tags/v{config['version']}, got {ref}")


def preflight(
    ref: str, publish: bool, root: Path = ROOT, *, tag: str = ""
) -> dict[str, str]:
    """Resolve a version tag and return Actions outputs without publishing.

    Use the explicit tag for a manual run, otherwise the event ref, and read
    wheel.json from that commit. A tag push must still point to checked-out
    HEAD. Both modes require the selected tag to match its configured version.

    Publishing additionally requires the commit to be contained in origin/main;
    manual publication must run from main or the target tag. Validation alone
    permits unmerged commits. The checkout at root must contain the required
    refs and history. Invalid selections and failed Git commands propagate.
    """
    source_ref = ref
    if tag:
        if not tag.startswith("v"):
            raise ValueError("Enter an existing version tag such as v0.7.4")
        canonical_version(tag[1:])
        source_ref = f"refs/tags/{tag}"
        if publish and ref not in ("refs/heads/main", source_ref):
            raise ValueError("Select main under 'Use workflow from' to publish a tag")
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", source_ref + "^{commit}"],
        cwd=root,
        text=True,
    ).strip()
    if not tag:
        event_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        if commit != event_commit:
            raise ValueError("The version tag no longer points to the selected commit")
    config = json.loads(
        subprocess.check_output(
            ["git", "show", f"{commit}:wheel.json"], cwd=root, text=True
        )
    )
    validate_ref(config, source_ref)
    if publish:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main"],
            cwd=root,
            check=True,
        )
    return {
        "publish_requested": str(publish).lower(),
        "version": config["version"],
        "source_ref": source_ref,
        "source_commit": commit,
    }


def main() -> None:
    """Validate the CLI release selection and write Actions outputs and summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--publish", choices=["true", "false"], required=True)
    args = parser.parse_args()
    selected = preflight(args.ref, args.publish == "true", tag=args.tag)
    outputs(**selected)
    summary(
        f"Selected version {selected['version']} from {selected['source_ref']} "
        f"at {selected['source_commit']}; publish={args.publish}."
    )


if __name__ == "__main__":
    main()
