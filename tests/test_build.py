"""Exercise the real wheel pipeline with synthetic upstream archives."""

import base64
import csv
import email
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build
from scripts.smoke import run_smoke
from scripts.upstream import archive_name

CONFIG = json.loads((build.ROOT / "wheel.json").read_text())
LICENSE = b"upstream license fixture\r\n"
MANUAL = b".TH AG-CLI 1\n"
# This stand-in verifies packaging/install wiring, not the real upstream runtime.
STAND_IN = (
    f"#!{sys.executable}\n"
    "import sys\n"
    "args = sys.argv[1:]\n"
    "if args == ['--version']:\n"
    "    print('ag-cli version v0.7.4 (commit: abc123, built: 2026-10-01T00:00:00Z)')\n"
    "elif args == ['version', '--json']:\n"
    '    print(\'{"version": "v0.7.4", "commit": "abc123", "buildDate": "2026-10-01T00:00:00Z"}\')\n'
    "elif args == ['--help']:\n"
    "    print('ag-cli auth repo pr issue')\n"
    "elif args == ['completion', 'bash']:\n"
    "    print('complete -F __start_ag-cli ag-cli')\n"
    "else:\n"
    "    sys.exit(2)\n"
).encode()


def archive_blob(target, files=None):
    if files is None:
        binary = "ag-cli.exe" if target.startswith("windows_") else "ag-cli"
        files = {binary: STAND_IN, "LICENSE": LICENSE}
        if not target.startswith("windows_"):
            files["share/man/man1/ag-cli.1"] = MANUAL
    stream = io.BytesIO()
    if target.startswith("windows_"):
        with zipfile.ZipFile(stream, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
    else:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return stream.getvalue()


def release_assets():
    targets = {
        Path(entries[0]["path"]).parent.name for entries in CONFIG["binaries"].values()
    }
    assets = {archive_name(target): archive_blob(target) for target in targets}
    assets["checksums.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(assets.items())
    ).encode()
    return assets


class BuildTests(unittest.TestCase):
    def run_build(self, root, arguments, assets):
        (root / "wheel.json").write_text(json.dumps(CONFIG))
        (root / "README.md").write_text("# Test distribution\n")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES"):
            shutil.copyfile(build.ROOT / name, root / name)
        with (
            patch("build.ROOT", root),
            patch("sys.argv", ["build.py", *arguments]),
            patch(
                "build.fetch", side_effect=lambda url: assets[url.rsplit("/", 1)[1]]
            ) as fetch,
        ):
            build.main()
        return fetch

    def test_all_platforms_preserve_bytes_permissions_metadata_and_record(self):
        assets = release_assets()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "dist"
            fetch = self.run_build(root, ["--output-dir", str(output)], assets)
            self.assertEqual(fetch.call_count, 7)
            self.assertEqual(
                {call.args[0] for call in fetch.call_args_list},
                {
                    f"{CONFIG['homepage']}/releases/download/v0.7.4/{name}"
                    for name in assets
                },
            )
            wheels = list(output.glob("*.whl"))
            self.assertEqual(len(wheels), 8)
            self.assertEqual(
                {wheel.name.rsplit("-", 1)[1][:-4] for wheel in wheels},
                set(CONFIG["binaries"]),
            )
            for wheel in wheels:
                with self.subTest(wheel=wheel.name), zipfile.ZipFile(wheel) as archive:
                    names = archive.namelist()
                    executable = next(
                        name for name in names if ".data/scripts/" in name
                    )
                    self.assertTrue(
                        executable.endswith(
                            "/ag-cli.exe" if "-win_" in wheel.name else "/ag-cli"
                        )
                    )
                    self.assertEqual(archive.read(executable), STAND_IN)
                    self.assertEqual(
                        (archive.getinfo(executable).external_attr >> 16) & 0o777, 0o755
                    )
                    license_path = next(
                        name for name in names if name.endswith("/licenses/LICENSE")
                    )
                    self.assertEqual(archive.read(license_path), LICENSE)
                    self.assertFalse(any("/share/man/" in name for name in names))
                    metadata = email.message_from_bytes(
                        archive.read(
                            next(name for name in names if name.endswith("/METADATA"))
                        )
                    )
                    self.assertEqual(metadata.defects, [])
                    self.assertEqual(metadata["Name"], "ag-cli-py")
                    self.assertEqual(metadata["Version"], "0.7.4")
                    self.assertIsNone(metadata["Requires-Dist"])
                    self.assertEqual(metadata["Metadata-Version"], "2.4")
                    self.assertIsNone(metadata["License"])
                    self.assertEqual(metadata["License-Expression"], CONFIG["license"])
                    self.assertEqual(
                        metadata.get_all("License-File"),
                        ["LICENSE", "PACKAGING-LICENSE", "THIRD_PARTY_NOTICES"],
                    )
                    for name, source in (
                        ("PACKAGING-LICENSE", "LICENSE"),
                        ("THIRD_PARTY_NOTICES", "THIRD_PARTY_NOTICES"),
                    ):
                        path = license_path.removesuffix("LICENSE") + name
                        self.assertEqual(
                            archive.read(path), (root / source).read_bytes()
                        )
                    self.assertIn("# Test distribution\n", metadata.get_payload())
                    self.assertIn(
                        "https://github.com/hust-open-atom-club/atomgit-cli/releases/tag/v0.7.4)",
                        metadata.get_payload(),
                    )
                    record_path = next(
                        name for name in names if name.endswith("/RECORD")
                    )
                    rows = list(
                        csv.reader(io.StringIO(archive.read(record_path).decode()))
                    )
                    self.assertEqual({row[0] for row in rows}, set(names))
                    for name, digest, size in rows:
                        if name == record_path:
                            self.assertEqual((digest, size), ("", ""))
                        else:
                            content = archive.read(name)
                            expected = (
                                base64.urlsafe_b64encode(
                                    hashlib.sha256(content).digest()
                                )
                                .rstrip(b"=")
                                .decode()
                            )
                            self.assertEqual(digest, "sha256=" + expected)
                            self.assertEqual(int(size), len(content))
            subprocess.run(
                [sys.executable, "-m", "twine", "check", "--strict", *map(str, wheels)],
                check=True,
                capture_output=True,
            )
            if sys.platform.startswith("linux") and os.uname().machine == "x86_64":
                report = run_smoke(
                    next(output.glob("*-manylinux_2_17_x86_64.whl")), "0.7.4"
                )
                self.assertEqual(report["build"]["version"], "v0.7.4")

    def test_repeated_target_downloads_once_per_run_and_builds_both_linux_wheels(self):
        assets = release_assets()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "dist"
            arguments = [
                "--target",
                "linux_amd64",
                "--target",
                "linux_amd64",
                "--output-dir",
                str(output),
            ]
            fetch = self.run_build(root, arguments, assets)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(list(output.glob("*.whl"))), 2)
            fetch = self.run_build(
                root, ["--target", "linux_amd64", "--prepare-only"], assets
            )
            self.assertEqual(fetch.call_count, 2)

    def test_prepare_windows_without_readme_and_removes_stale_licenses(self):
        assets = release_assets()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "build/windows_arm64/licenses/stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("old")
            self.run_build(
                root, ["--target", "windows_arm64", "--prepare-only"], assets
            )
            self.assertFalse(stale.exists())
            self.assertEqual(
                (root / "build/windows_arm64/ag-cli.exe").read_bytes(), STAND_IN
            )
            self.assertFalse((root / "dist").exists())

    def test_corrupt_or_missing_checksum_never_writes_binary(self):
        for manifest in (b"", b"0" * 64 + b"  ag_linux_amd64.tar.gz\n"):
            with (
                self.subTest(manifest=manifest),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                assets = release_assets()
                assets["checksums.txt"] = manifest
                with self.assertRaises((KeyError, ValueError)):
                    self.run_build(
                        root, ["--target", "linux_amd64", "--prepare-only"], assets
                    )
                self.assertFalse((root / "build/linux_amd64/ag-cli").exists())

    def test_missing_or_empty_required_file_fails_before_writing(self):
        for files in (
            {"LICENSE": LICENSE},
            {"LICENSE": LICENSE, "ag-cli": b""},
            {"ag-cli": STAND_IN},
            {"LICENSE": b"", "ag-cli": STAND_IN},
        ):
            data = archive_blob("linux_amd64", files)
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch("build.fetch", return_value=data),
            ):
                executable = Path(temporary) / "target/ag-cli"
                with self.assertRaises((KeyError, ValueError)):
                    build.prepare_target(
                        CONFIG["homepage"],
                        "v0.7.4",
                        "linux_amd64",
                        executable,
                        {"ag_linux_amd64.tar.gz": hashlib.sha256(data).hexdigest()},
                    )
                self.assertFalse(executable.exists())

    def test_checksum_manifest_rejects_malformed_and_duplicate_entries(self):
        digest = "a" * 64
        self.assertEqual(
            build.parse_checksums(f"{digest} *file.zip\n".encode()),
            {"file.zip": digest},
        )
        for text in ("bad  file.zip", f"{digest}  file.zip\n{digest}  file.zip\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                build.parse_checksums(text.encode())

    def test_archive_paths_cannot_escape_the_document_directory(self):
        files = {
            "ag-cli": STAND_IN,
            "LICENSE": LICENSE,
            "share/man/man1/ag-cli.1": MANUAL,
            "share/man/man1/../../outside.1": b"unexpected",
            "share/man/man1/..\\outside.1": b"unexpected",
            "../outside.1": b"unexpected",
        }
        data = archive_blob("linux_amd64", files)
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("build.fetch", return_value=data),
        ):
            root = Path(temporary)
            licenses = build.prepare_target(
                CONFIG["homepage"],
                "v0.7.4",
                "linux_amd64",
                root / "target/ag-cli",
                {"ag_linux_amd64.tar.gz": hashlib.sha256(data).hexdigest()},
            )
            self.assertEqual(
                {
                    path.relative_to(licenses).as_posix()
                    for path in licenses.rglob("*")
                    if path.is_file()
                },
                {
                    "LICENSE",
                    "PACKAGING-LICENSE",
                    "THIRD_PARTY_NOTICES",
                },
            )
            self.assertFalse(list(root.rglob("outside.1")))


if __name__ == "__main__":
    unittest.main()
