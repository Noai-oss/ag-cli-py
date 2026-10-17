# ag-cli-py

[AtomGit CLI](https://atomgit.com/hust-open-atom-club/atomgit-cli) manages AtomGit repositories, pull requests, issues, releases, and workflows from the terminal.

This unofficial Python distribution packages the original prebuilt binaries. The packaging source code is available in [Noai-oss/ag-cli-py](https://github.com/Noai-oss/ag-cli-py).

Once published, install it with:

```sh
uv tool install ag-cli-py
ag-cli --help
```

## Platforms

| OS | Architectures | Wheel baseline |
| --- | --- | --- |
| macOS | x86_64, arm64 | macOS 12 |
| Linux (glibc) | x86_64, aarch64 | manylinux 2.17 |
| Linux (musl) | x86_64, aarch64 | musllinux 1.2 |
| Windows | x86_64, arm64 | Windows 10 or later |

Linux glibc and musl wheels share the same statically linked executable. The listed versions are distribution baselines; minimum system compatibility has not been tested. See [validation details](CONTRIBUTING.md#platform-baselines).

Upstream also provides LoongArch64 binaries. They are excluded from this distribution because [PyPI's platform validation](https://github.com/pypi/warehouse/blob/main/warehouse/utils/wheel.py) does not currently allow `loongarch64` for either manylinux or musllinux (checked 2026-10-17).

## Usage and updates

Run `ag-cli auth login` to authenticate. For CLI documentation and issues, see the [upstream project](https://atomgit.com/hust-open-atom-club/atomgit-cli).

Upgrade this distribution through your Python package manager:

```sh
uv tool upgrade ag-cli-py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for local builds, checks, and release workflows.

## License

The packaging code and project documentation use [Apache-2.0](LICENSE). The unmodified AtomGit CLI executable uses [MulanPSL-2.0](https://github.com/hust-open-atom-club/atomgit-cli/blob/v0.7.4/LICENSE); bundled components retain their respective licenses, reproduced in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

Each wheel includes the original upstream `LICENSE`, `PACKAGING-LICENSE`, and `THIRD_PARTY_NOTICES` under `.dist-info/licenses/`.
