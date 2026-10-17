# SPDX-License-Identifier: Apache-2.0
# Modified for AtomGit CLI packaging and license preservation.
"""Package upstream binaries and license notices as wheels."""

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from postprocess import postprocess
from scripts.upstream import COMMAND, archive_name, fetch, stable_version

ROOT = Path(__file__).resolve().parent


def archive_files(data: bytes, names: tuple[str, ...]) -> dict[str, bytes]:
    """Read only required ZIP or tar.gz members, without extracting paths."""
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as archive:
            return {name: archive.read(name) for name in names}
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:gz") as archive:
        return {
            name: archive.extractfile(name).read()
            for name in names
            if archive.getmember(name).isfile()
        }


def parse_checksums(data: bytes) -> dict[str, str]:
    """Read the upstream SHA-256 manifest, rejecting ambiguous entries."""
    checksums = {}
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](\S+)", line)
        if not match or match[2] in checksums:
            raise ValueError(f"Invalid or duplicate checksum entry: {line!r}")
        checksums[match[2]] = match[1].lower()
    return checksums


def prepare_target(
    upstream: str, tag: str, target: str, executable: Path, checksums: dict[str, str]
) -> Path:
    """Save the executable and return its license directory."""
    name = archive_name(target)
    url = f"{upstream}/releases/download/{tag}/{name}"
    print(f"Preparing {target}...", flush=True)
    expected = checksums[name]
    data = fetch(url)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {name}")
    binary_name = COMMAND + (".exe" if target.startswith("windows_") else "")
    files = archive_files(data, (binary_name, "LICENSE"))
    binary = files[binary_name]
    if not binary:
        raise ValueError(f"Empty executable in {name}")
    license_text = files["LICENSE"]
    if not license_text.strip():
        raise ValueError(f"Empty LICENSE in {name}")
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(binary)
    executable.chmod(0o755)
    licenses = executable.parent / "licenses"
    if licenses.exists():
        shutil.rmtree(licenses)
    licenses.mkdir()
    (licenses / "LICENSE").write_bytes(license_text)
    shutil.copyfile(ROOT / "LICENSE", licenses / "PACKAGING-LICENSE")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES", licenses / "THIRD_PARTY_NOTICES")
    return licenses


def main() -> None:
    """Prepare selected upstream targets and optionally build finished wheels."""
    config_path = ROOT / "wheel.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # Each platform has one executable at build/<upstream-target>/<filename>.
    executables = {
        Path(entries[0]["path"]).parent.name: ROOT / entries[0]["path"]
        for entries in config["binaries"].values()
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        choices=executables,
        help="Repeat to select targets; default: all",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Download binaries and licenses without building wheels",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    # Download each target once, even when requested more than once.
    targets = dict.fromkeys(args.target or executables)
    binaries = {
        platform: entries
        for platform, entries in config["binaries"].items()
        if Path(entries[0]["path"]).parent.name in targets
    }
    licenses = {}
    upstream = config["homepage"].rstrip("/")
    tag = "v" + config["version"]
    stable_version(tag)
    checksums = parse_checksums(
        fetch(f"{upstream}/releases/download/{tag}/checksums.txt")
    )
    for target in targets:
        licenses[target] = prepare_target(
            upstream, tag, target, executables[target], checksums
        )

    if args.prepare_only:
        print("Prepared binaries and licenses in build/.")
        return

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme += (
        f"\nUpstream release: [{tag}]({upstream}/releases/{tag}).\n"
        f"Source: [{tag}]({upstream}/tree/{tag}).\n"
    )

    # Keep raw wheels temporary; only finished wheels reach the output directory.
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        # Always use absolute paths, including when called outside the repo root.
        selected = {
            **config,
            "binaries": {
                platform: [
                    {**entry, "path": str(ROOT / entry["path"])} for entry in entries
                ]
                for platform, entries in binaries.items()
            },
        }
        config_path = work / "wheel.json"
        config_path.write_text(json.dumps(selected), encoding="utf-8")
        raw = work / "raw"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bin2whl",
                "--config",
                str(config_path),
                "--output-dir",
                str(raw),
            ],
            check=True,
        )
        for platform, entries in binaries.items():
            wheel = next(raw.glob(f"*-{platform}.whl"))
            target = Path(entries[0]["path"]).parent.name
            print(postprocess(wheel, licenses[target], readme, args.output_dir))


if __name__ == "__main__":
    try:
        main()
    except (
        KeyError,
        OSError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
