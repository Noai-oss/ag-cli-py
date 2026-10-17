# SPDX-License-Identifier: Apache-2.0
# Modified for AtomGit CLI packaging and license metadata.
"""Add licenses and a PyPI description using the wheel unpack/pack CLI."""

import email.policy
import shutil
import subprocess
import sys
import tempfile
from email.parser import BytesParser
from pathlib import Path

from packaging.licenses import canonicalize_license_expression


def postprocess(wheel: Path, licenses: Path, readme: str, output: Path) -> Path:
    """Process a bin2whl wheel with no README body and return the output path."""
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        work = Path(temporary)
        # wheel unpack preserves executable permissions from bin2whl.
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", str(wheel), "--dest", str(work)],
            check=True,
        )
        unpacked = next(work.iterdir())
        dist_info = next(unpacked.glob("*.dist-info"))
        shutil.copytree(licenses, dist_info / "licenses")
        # bin2whl 1.0.2 emits Metadata 2.1 and omits the header/body separator.
        metadata = dist_info / "METADATA"
        headers = BytesParser().parsebytes(metadata.read_bytes())
        headers.replace_header("Metadata-Version", "2.4")
        headers["License-Expression"] = str(
            canonicalize_license_expression(headers["License"])
        )
        del headers["License"]
        licenses = dist_info / "licenses"
        for path in sorted(licenses.rglob("*")):
            if path.is_file():
                headers["License-File"] = path.relative_to(licenses).as_posix()
        headers["Description-Content-Type"] = "text/markdown"
        metadata.write_bytes(
            headers.as_bytes(policy=email.policy.compat32.clone(max_line_length=0))
            + readme.encode("utf-8")
        )
        # wheel pack rebuilds RECORD to include the new and modified files.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "wheel",
                "pack",
                str(unpacked),
                "--dest-dir",
                str(work),
            ],
            check=True,
        )
        result = next(work.glob("*.whl"))
        destination = output / result.name
        # Replace the existing wheel only after packing succeeds.
        result.replace(destination)
    return destination
