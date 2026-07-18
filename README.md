# Flet Build Action

Build and archive Flet apps in GitHub Actions.

This action wraps `flet build` with CI-focused defaults:

- resolves the Flet and Flutter toolchain before the build;
- validates that the selected target can run on the current runner;
- optionally installs Flet-reported Linux desktop dependencies;
- caches uv, Flutter, and Flet downloads;
- exposes the raw build output directory for signing or deployment steps;
- creates one predictable archive file for upload.

## Example

```yaml
name: Build Flet App

on:
  push:
  workflow_dispatch:

jobs:
  build-apk:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v6

      - name: Build APK
        id: build
        uses: flet-dev/flet-build-action@v1
        with:
          target: apk
          runner-python-version: "3.14"
          bundled-python-version: "3.14"
          build-number: ${{ github.run_number }}

      - name: Upload APK
        uses: actions/upload-artifact@v7
        with:
          path: ${{ steps.build.outputs.archive-path }}
          archive: false
          if-no-files-found: error
```

Setting `archive: false` on the `actions/upload-artifact` step is intentional.
This action already creates a platform-aware archive before upload, preserving
the packaging details that matter for each target: Android APK/AAB outputs and
checksums stay together, Apple app bundles keep their bundle metadata, and
Linux outputs use tar.gz to preserve permissions and symlinks.

## Requirements

Your project must contain a `pyproject.toml` file. Keep persistent Flet build
configuration there, for example under `[tool.flet]`.

For target-specific packaging, signing, and deployment guidance, see the
[Flet publishing docs](https://flet.dev/docs/publish/).

The workflow must check out your repository before running this action:

```yaml
- uses: actions/checkout@v6
```

## Supported Targets

| Target          | Runner                   |
|-----------------|--------------------------|
| `apk`           | Linux, macOS, or Windows |
| `aab`           | Linux, macOS, or Windows |
| `web`           | Linux, macOS, or Windows |
| `linux`         | Linux                    |
| `windows`       | Windows                  |
| `macos`         | macOS                    |
| `ipa`           | macOS                    |
| `ios-simulator` | macOS                    |

Use [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for--private-repositories)
that have the platform toolchain required by the target. Apple targets (`macos`, `ipa` & `ios-simulator`) require macOS.
`windows` target requires Windows. Linux desktop builds require Linux system
packages, which the action can install on Debian-based runners with `apt-get`.

## Inputs

| Input                        | Required | Default                        | Description                                                                                                                                                                                                                                                              |
|------------------------------|----------|--------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `target`                     | Yes      | None                           | Target passed to `flet build`. One of `apk`, `aab`, `ipa`, `ios-simulator`, `macos`, `linux`, `windows`, or `web`. See [docs](https://flet.dev/docs/publish/#platform-matrix).                                                                                           |
| `working-directory`          | No       | `.`                            | Directory containing the Flet project's `pyproject.toml`. Relative paths are resolved from the repository workspace. See [docs](https://flet.dev/docs/publish/#project-structure).                                                                                       |
| `runner-python-version`      | No       | Project configuration          | Python interpreter used by uv to resolve the project environment and run the Flet CLI, for example `3.12`. This does not control the Python bundled into the Flet app at build time.                                                                                     |
| `bundled-python-version`     | No       | Flet resolution                | Python version bundled into the app, for example `3.12` or `3.13`. This is passed to `flet build --python-version`. See [docs](https://flet.dev/docs/publish/#choosing-a-python-version).                                                                                |
| `build-number`               | No       | Project/template configuration | Internal, incrementing build identifier. `${{ github.run_number }}` is a common value. See [docs](https://flet.dev/docs/publish/#build-number).                                                                                                                          |
| `build-version`              | No       | Project/template configuration | User-facing release version, for example `1.4.0`. This is passed to `flet build --build-version`. See [docs](https://flet.dev/docs/publish/#build-version).                                                                                                              |
| `output-directory`           | No       | `build/<target>`               | Raw build output directory. Relative paths are resolved from `working-directory`. Flet recreates this directory for each build. See [docs](https://flet.dev/docs/publish/#output-directory).                                                                             |
| `extra-args`                 | No       | Empty                          | Additional `flet build` arguments parsed as a shell-like string without shell evaluation. Use dedicated inputs for output and version options. See [docs](https://flet.dev/docs/cli/flet-build/).                                                                        |
| `cache`                      | No       | `true`                         | Cache uv downloads, the required Flutter SDK, and Flet downloads. Set to `false` while troubleshooting cache issues or when managing caches separately.                                                                                                                  |
| `install-linux-dependencies` | No       | `true`                         | Install Flet-reported apt packages for Linux desktop builds. Set to `false` for pre-provisioned or non-Debian Linux runners. Ignored for non-Linux targets. See [docs](https://flet.dev/docs/publish/linux/#prerequisites).                                              |
| `archive-output`             | No       | `true`                         | Create one platform-aware archive after the build. When using `actions/upload-artifact`, keep `archive-output` enabled and set `upload-artifact`'s `archive` option to `false`. Set `archive-output` to `false` only if a later step will package the raw output itself. |

## Outputs

| Output            | Description                                                                                                                                         |
|-------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `output-path`     | Absolute path to the raw directory produced by `flet build`. Use this for signing, deployment, or custom processing in later steps of the same job. |
| `archive-path`    | Absolute path to the generated ZIP or tar.gz archive. Empty when `archive-output` is `false`.                                                       |
| `flet-version`    | Resolved Flet CLI version used for the build.                                                                                                       |
| `flutter-version` | Flutter SDK version required by the resolved Flet version.                                                                                          |

## Archives

When `archive-output` is enabled, the action produces an archive file
(accessible as `archive-path`), which contains the raw build output and any checksum files.
The archive name is predictable and depends on the target:

| Target          | Archive                  |
|-----------------|--------------------------|
| `apk`           | `flet-apk.zip`           |
| `aab`           | `flet-aab.zip`           |
| `ipa`           | `flet-ipa.zip`           |
| `ios-simulator` | `flet-ios-simulator.zip` |
| `macos`         | `flet-macos.zip`         |
| `windows`       | `flet-windows.zip`       |
| `web`           | `flet-web.zip`           |
| `linux`         | `flet-linux.tar.gz`      |

The raw build output always remains available at `output-path` for later steps
in the same job.

## Matrix/Cross-platform Example

Use a matrix when you intentionally want to build multiple targets in one
workflow.

```yaml
jobs:
  build:
    name: Build ${{ matrix.target }}
    runs-on: ${{ matrix.runner }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - target: apk
            runner: ubuntu-latest
          - target: aab
            runner: ubuntu-latest
          - target: web
            runner: ubuntu-latest
          - target: linux
            runner: ubuntu-latest
          - target: windows
            runner: windows-latest
          - target: macos
            runner: macos-latest
          - target: ipa
            runner: macos-latest
          - target: ios-simulator
            runner: macos-latest

    steps:
      - uses: actions/checkout@v6

      - name: Build ${{ matrix.target }}
        id: build
        uses: flet-dev/flet-build-action@v1
        with:
          target: ${{ matrix.target }}
          runner-python-version: "3.14"
          bundled-python-version: "3.14"
          build-number: ${{ github.run_number }}

      - name: Upload build archive
        uses: actions/upload-artifact@v7
        with:
          path: ${{ steps.build.outputs.archive-path }}
          archive: false
          if-no-files-found: error
```

## Signing and Deployment

For signing, notarization, store upload, or custom deployment, use
`output-path` before uploading the final archive. The
[Flet publishing documentation](https://flet.dev/docs/publish/) covers the
platform-specific requirements. For example:

```yaml
- name: Build macOS app
  id: build
  uses: flet-dev/flet-build-action@v1
  with:
    target: macos

- name: Sign app
  run: ./scripts/sign-macos.sh "${{ steps.build.outputs.output-path }}"
```

## Development

Run the local checks:

```bash
uv run pytest
uv run ruff check scripts tests
uv run ruff format --check scripts tests
```

The manual [`build-smoke-test.yml`](.github/workflows/build-smoke-test.yml) workflow
builds a generated sample app across the supported targets. Use it before cutting a release tag.
