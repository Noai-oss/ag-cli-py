# Building and publishing

Use Python 3.12 and uv. Package versions and platforms are configured in `wheel.json`; build dependencies are locked in `uv.lock`.

```sh
uv sync --locked
uv run --locked python build.py
```

The build downloads official archives and `checksums.txt`, verifies SHA-256, and writes eight wheels to `dist/`. Each wheel contains the unmodified executable, license notices, and package metadata. Intermediate files in `build/<target>/` contain only the executable and `licenses/`; `build/` and `dist/` are not committed.

```sh
uv run --locked python build.py --target linux_amd64
uv run --locked python build.py --prepare-only
```

Repeat `--target` to select multiple targets. `--output-dir PATH` changes the finished wheel destination. `--prepare-only` stops after downloading and preparing files.

## Validation

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked twine check dist/*.whl
uv run --locked python -m scripts.smoke dist/*-manylinux_2_17_x86_64.whl
```

Tests check packaging, checksums, license preservation, metadata, updates and release selection using synthetic archives. CI also installs real wheels and runs the CLI on Linux x86_64, macOS ARM64 and Windows x86_64. Smoke checks use temporary configuration and require no login.

## Platform baselines

The v0.7.4 Linux release binaries were checked against the official checksums and inspected with `file` and `readelf -W -h -l -d -V`: they are statically linked, with no dynamic interpreter, library dependencies or GLIBC symbol versions. The manylinux 2.17 and musllinux 1.2 tags describe the selected Python distribution baselines; the executable has no dynamic libc requirement.

The macOS 12 baseline follows upstream's [Go 1.26 toolchain](https://go.dev/doc/go1.26#darwin). Minimum OS and kernel compatibility have not been tested. LoongArch wheels are excluded because [PyPI's platform validator](https://github.com/pypi/warehouse/blob/main/warehouse/utils/wheel.py) does not accept their tags (checked 2026-10-17).

## Updates and releases

```sh
uv run --locked python -m scripts.update_version
```

The Update workflow runs daily or manually and opens a version-only PR when all required release assets are present. Enable GitHub Actions to create pull requests in repository settings. Public upstream requests need no token; an optional `ATOMGIT_TOKEN` secret is supported. Review platform and license changes before merging an update.

A `v*` tag push publishes after validation. The tag must match the version in `wheel.json`, and the tagged commit must be on `main`. For a manual check, run **Actions → Release** from `main`, supply an existing tag, and leave **publish** unchecked.

Before publishing, configure the PyPI Trusted Publisher for project `ag-cli-py`, owner `Noai-oss`, repository `ag-cli-py`, workflow `release.yml`, and GitHub environment `pypi`. Publication uses the exact wheel artifact tested by CI. For a partial upload failure, rerun failed jobs in the original run to reuse that artifact.

## Licenses

Packaging code and documentation use Apache-2.0. The build preserves upstream's original `LICENSE` and bundles it with `PACKAGING-LICENSE` and `THIRD_PARTY_NOTICES`. Wheel metadata declares their license expression and file paths; repacking regenerates `RECORD`.

When updating upstream, check its license and linked dependency/toolchain versions, then refresh `THIRD_PARTY_NOTICES` and the license expression in `wheel.json` as needed.
