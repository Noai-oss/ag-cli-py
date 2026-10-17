"""Install a local wheel and exercise AtomGit CLI without network or login."""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from scripts.common import ROOT, summary
from scripts.upstream import COMMAND, stable_version


def cli_version(output: str) -> str:
    match = re.fullmatch(
        r"ag-cli version (v[0-9]+\.[0-9]+\.[0-9]+)(?: \([^\r\n]+\))?\s*", output
    )
    if not match:
        raise ValueError(f"Unrecognized ag-cli version output: {output!r}")
    return stable_version(match[1])


def check_version_json(output: str, version: str) -> dict:
    info = json.loads(output)
    if not isinstance(info, dict) or info.get("version") != "v" + version:
        raise ValueError(f"Binary JSON version differs from wheel.json: {output!r}")
    for name in ("commit", "buildDate"):
        if not isinstance(info.get(name), str) or info[name] in ("", "unknown"):
            raise ValueError(f"Missing release build metadata: {name}")
    return info


def run_cli(arguments: list[str], work: Path) -> subprocess.CompletedProcess[str]:
    # Isolate user configuration, aliases and credentials from the smoke test.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AG_", "ATOMGIT_", "GITCODE_"))
    }
    environment.update(
        HOME=str(work),
        USERPROFILE=str(work),
        XDG_CONFIG_HOME=str(work / "config"),
        APPDATA=str(work / "config"),
    )
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        cwd=work,
        env=environment,
    )
    if result.returncode:
        summary(f"CLI failed:\n{result.stdout}\n{result.stderr}")
        result.check_returncode()
    return result


def run_smoke(wheel: Path, version: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="ag-cli-smoke-") as temporary:
        work = Path(temporary)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        executable = scripts / (COMMAND + (".exe" if os.name == "nt" else ""))
        subprocess.run(
            [
                "uv",
                "--no-cache",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-index",
                "--no-deps",
                str(wheel.resolve()),
            ],
            check=True,
            timeout=120,
        )
        result = run_cli([str(executable), "--version"], work)
        if cli_version(result.stdout) != version:
            raise ValueError(
                f"Binary version differs from wheel.json: {result.stdout!r}"
            )
        info = check_version_json(
            run_cli([str(executable), "version", "--json"], work).stdout, version
        )
        help_output = run_cli([str(executable), "--help"], work).stdout
        if "ag-cli" not in help_output or "auth" not in help_output:
            raise ValueError("Root help does not describe AtomGit CLI")
        completion = run_cli([str(executable), "completion", "bash"], work).stdout
        if "ag-cli" not in completion or "complete" not in completion:
            raise ValueError("Bash completion generation failed")
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "wheel": wheel.name,
        "version_output": result.stdout.strip(),
        "build": info,
        "checks": ["--version", "version --json", "--help", "completion bash"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / "wheel.json").read_text(encoding="utf-8"))
    report = run_smoke(args.wheel, config["version"])
    summary("Installed and ran the local wheel:\n\n" + json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
