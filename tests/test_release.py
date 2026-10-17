"""Test version tag selection and publication eligibility."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.release import preflight, validate_ref


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        """Create a temporary repository with a tagged commit on origin/main."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-b", "main")
        self.first = self.commit_version("0.7.4")
        self.git("tag", "v0.7.4")
        self.git("update-ref", "refs/remotes/origin/main", self.first)

    def git(self, *args):
        """Run Git in the test repository with signing and hooks disabled."""
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=self.root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    def commit_version(self, version):
        """Commit a wheel.json version in the test repository and return its SHA."""
        (self.root / "wheel.json").write_text(json.dumps({"version": version}))
        self.git("add", "wheel.json")
        self.git("commit", "--allow-empty", "-m", version)
        return self.git("rev-parse", "HEAD")

    def test_web_selects_tag_config_and_commit_instead_of_main(self):
        """Resolve the selected tag even when main advances or a branch shares its name."""
        second = self.commit_version("0.8.0")
        self.git("tag", "-a", "v0.8.0", "-m", "annotated")
        latest = self.commit_version("0.9.0")
        self.git("update-ref", "refs/remotes/origin/main", latest)
        self.git("branch", "v0.7.4")
        for version, commit in (("0.7.4", self.first), ("0.8.0", second)):
            with self.subTest(version=version):
                self.assertEqual(
                    preflight("refs/heads/main", True, self.root, tag=f"v{version}"),
                    {
                        "publish_requested": "true",
                        "version": version,
                        "source_ref": f"refs/tags/v{version}",
                        "source_commit": commit,
                    },
                )
        self.assertEqual(self.git("rev-parse", "HEAD"), latest)

    def test_tag_push_supports_lightweight_and_annotated_tags(self):
        """Resolve both tag forms to the same underlying release commit."""
        for annotated in (False, True):
            with self.subTest(annotated=annotated):
                if annotated:
                    self.git("tag", "-f", "-a", "v0.7.4", "-m", "annotated")
                result = preflight("refs/tags/v0.7.4", True, self.root)
                self.assertEqual(result["source_commit"], self.first)

    def test_tag_push_rejects_a_moved_tag(self):
        """Block a tag whose current target differs from the event checkout."""
        self.commit_version("0.7.4")
        self.git("tag", "-f", "v0.7.4")
        self.git("checkout", "--detach", self.first)
        with self.assertRaisesRegex(ValueError, "no longer points"):
            preflight("refs/tags/v0.7.4", True, self.root)

    def test_unmerged_tag_can_be_validated_but_not_published(self):
        """Allow validation of a branch release while blocking its publication."""
        self.git("checkout", "-b", "unmerged")
        commit = self.commit_version("0.8.0")
        self.git("tag", "v0.8.0")
        result = preflight("refs/heads/main", False, self.root, tag="v0.8.0")
        self.assertEqual(result["source_commit"], commit)
        self.assertEqual(result["publish_requested"], "false")
        with self.assertRaises(subprocess.CalledProcessError):
            preflight("refs/heads/main", True, self.root, tag="v0.8.0")
        with self.assertRaises(subprocess.CalledProcessError):
            preflight("refs/tags/v0.8.0", True, self.root)

    def test_web_rejects_invalid_missing_and_mismatched_tags(self):
        """Reject malformed inputs, nonexistent tags, and tag/version mismatches."""
        for tag in ("0.7.4", "refs/tags/v0.7.4", "v0.7.4^{commit}", "v0.7.4\n"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                preflight("refs/heads/main", False, self.root, tag=tag)
        self.git("branch", "v0.8.0")
        with self.assertRaises(subprocess.CalledProcessError):
            preflight("refs/heads/main", False, self.root, tag="v0.8.0")
        self.git("tag", "v0.8.0")
        with self.assertRaisesRegex(ValueError, "Expected refs/tags/v0.7.4"):
            preflight("refs/heads/main", False, self.root, tag="v0.8.0")

    def test_web_publishing_requires_workflow_from_main_or_target_tag(self):
        """Reject publication from a feature workflow but allow the target tag."""
        with self.assertRaisesRegex(ValueError, "Select main"):
            preflight("refs/heads/feature", True, self.root, tag="v0.7.4")
        result = preflight("refs/tags/v0.7.4", True, self.root, tag="v0.7.4")
        self.assertEqual(result["source_commit"], self.first)


class ReleaseTests(unittest.TestCase):
    def test_validation_and_publishing_require_exact_version_tag(self):
        """Reject branches and tags that do not exactly match wheel.json."""
        config = {"version": "0.7.4"}
        validate_ref(config, "refs/tags/v0.7.4")
        for ref in (
            "refs/heads/main",
            "refs/heads/v0.7.4",
            "refs/tags/v0.7",
            "refs/tags/v0.8.0",
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                validate_ref(config, ref)
