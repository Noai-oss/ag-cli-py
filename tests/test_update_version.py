"""Check GitHub release selection and atomic version updates."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import update_version
from scripts.common import ROOT
from scripts.upstream import asset_names

CONFIG = json.loads((ROOT / "wheel.json").read_text())


def release(version="0.8.0"):
    return {
        "tag_name": "v" + version,
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"{CONFIG['homepage']}/releases/download/v{version}/{name}"
                ),
            }
            for name in asset_names(CONFIG)
        ],
    }


class UpdateTests(unittest.TestCase):
    def test_updates_only_version_using_github_release_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wheel.json"
            path.write_text(json.dumps(CONFIG, indent=2) + "\n")
            report = path.with_suffix(".md")
            with patch.object(
                update_version, "latest_release", return_value=release()
            ) as latest:
                self.assertTrue(
                    update_version.update_version(path, "github-token", report)
                )
            latest.assert_called_once_with(
                "hust-open-atom-club/atomgit-cli", "github-token"
            )
            self.assertEqual(
                json.loads(path.read_text()), {**CONFIG, "version": "0.8.0"}
            )
            body = report.read_text()
            self.assertIn(
                "https://github.com/hust-open-atom-club/atomgit-cli/releases/tag/v0.8.0",
                body,
            )
            self.assertIn("`$atomgit-release-upgrade`", body)
            self.assertIn("`.agents/skills/atomgit-release-upgrade/SKILL.md`", body)

    def test_invalid_assets_leave_config_and_report_unchanged(self):
        for fault in ("missing", "duplicate", "http", "no_url", "no_checksums"):
            candidate = release()
            if fault == "missing":
                candidate["assets"].pop(0)
            elif fault == "duplicate":
                candidate["assets"].append(copy.deepcopy(candidate["assets"][0]))
            elif fault == "http":
                candidate["assets"][0]["browser_download_url"] = (
                    "http://example.org/file"
                )
            elif fault == "no_url":
                candidate["assets"][0].pop("browser_download_url")
            else:
                candidate["assets"] = [
                    item
                    for item in candidate["assets"]
                    if item["name"] != "checksums.txt"
                ]
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "wheel.json"
                original = json.dumps(CONFIG)
                path.write_text(original)
                report = path.with_suffix(".md")
                with (
                    patch.object(
                        update_version, "latest_release", return_value=candidate
                    ),
                    self.assertRaises((ValueError, KeyError)),
                ):
                    update_version.update_version(path, report_path=report)
                self.assertEqual(path.read_text(), original)
                self.assertFalse(report.exists())

    def test_no_update_does_not_require_assets_or_rewrite(self):
        for version in ("0.7.4", "0.7.3"):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = Path(temporary) / "wheel.json"
                original = json.dumps(CONFIG)
                path.write_text(original)
                with patch.object(
                    update_version,
                    "latest_release",
                    return_value={"tag_name": "v" + version},
                ):
                    self.assertFalse(update_version.update_version(path))
                self.assertEqual(path.read_text(), original)

    def test_api_failure_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wheel.json"
            original = json.dumps(CONFIG)
            path.write_text(original)
            with (
                patch.object(
                    update_version, "latest_release", side_effect=TimeoutError
                ),
                self.assertRaises(TimeoutError),
            ):
                update_version.update_version(path)
            self.assertEqual(path.read_text(), original)

    def test_latest_stable_uses_version_order_and_github_release_flags(self):
        values = [release("0.7.4"), release("0.10.0"), release("0.9.0")]
        values += [
            dict(release("8.0.0"), draft=True),
            dict(release("9.0.0"), prerelease=True),
        ]
        values += [
            {"tag_name": tag}
            for tag in ("v1.0.0rc1", "v1.0.0-beta.1", "v01.0.0", "snapshot", "v1.0")
        ]
        with patch.object(update_version, "get_json", return_value=values) as get:
            selected = update_version.latest_release("owner/repo", "github-token")
        self.assertEqual(selected["tag_name"], "v0.10.0")
        get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/releases?page=1&per_page=100",
            "github-token",
        )

    def test_pagination_is_not_limited_to_first_hundred_releases(self):
        first = [release(f"0.0.{index}") for index in range(100)]
        with patch.object(
            update_version, "get_json", side_effect=[first, [release("0.8.0")]]
        ) as get:
            selected = update_version.latest_release("owner/repo")
        self.assertEqual(selected["tag_name"], "v0.8.0")
        self.assertIn("page=2&", get.call_args.args[0])

    def test_repeated_pages_and_invalid_responses_fail(self):
        first = [release(f"0.0.{index}") for index in range(100)]
        with (
            patch.object(update_version, "get_json", side_effect=[first, first]),
            self.assertRaisesRegex(ValueError, "Repeated"),
        ):
            update_version.latest_release("owner/repo")
        for value in ([], {}, [dict(release(), prerelease=True)]):
            with (
                self.subTest(value=value),
                patch.object(update_version, "get_json", return_value=value),
                self.assertRaises((ValueError, TypeError)),
            ):
                update_version.latest_release("owner/repo")


class VersionBranchTests(unittest.TestCase):
    repo = "Noai-oss/ag-cli-py"
    api = f"https://api.github.com/repos/{repo}"

    def run_update(self, *, ref=False, status=404):
        candidate = "0.7.6"
        branch = f"update/atomgit-v{candidate}"

        def request(url, token):
            self.assertEqual(token, "token")
            if url == f"{self.api}/git/ref/heads/{branch}":
                if ref:
                    return {"ref": f"refs/heads/{branch}"}
                raise HTTPError(url, status, "mock response", {}, None)
            self.fail(f"Unexpected API request: {url}")

        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "wheel.json"
            original = json.dumps({**CONFIG, "version": "0.7.4"})
            config.write_text(original)
            report = config.with_suffix(".md")
            with (
                patch.object(
                    update_version, "latest_release", return_value=release(candidate)
                ),
                patch.object(update_version, "get_json", side_effect=request),
                patch.object(update_version, "outputs") as outputs,
            ):
                try:
                    changed = update_version.update_version(
                        config, "token", report, packaging_repository=self.repo
                    )
                except HTTPError:
                    self.assertEqual(config.read_text(), original)
                    self.assertFalse(report.exists())
                    raise

            if changed:
                self.assertEqual(
                    json.loads(config.read_text()), {**CONFIG, "version": candidate}
                )
                outputs.assert_called_once_with(
                    changed="true",
                    previous_version="0.7.4",
                    version=candidate,
                    branch=branch,
                )
                self.assertIn("atomgit-release-upgrade", report.read_text())
            else:
                self.assertEqual(config.read_text(), original)
                self.assertFalse(report.exists())
                outputs.assert_called_once_with(changed="false", version="0.7.4")
            return changed

    def test_existing_version_ref_is_not_reused(self):
        self.assertFalse(self.run_update(ref=True))

    def test_new_version_gets_its_own_branch(self):
        self.assertTrue(self.run_update())

    def test_reference_lookup_failure_does_not_write(self):
        with self.assertRaises(HTTPError):
            self.run_update(status=403)
