from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import NoReturn

TARGET_RUNNERS = {
    "aab": {"Linux", "macOS", "Windows"},
    "apk": {"Linux", "macOS", "Windows"},
    "ipa": {"macOS"},
    "ios-simulator": {"macOS"},
    "linux": {"Linux"},
    "macos": {"macOS"},
    "web": {"Linux", "macOS", "Windows"},
    "windows": {"Windows"},
}

BOOLEAN_VALUES = {"false": False, "true": True}


def fail(message: str) -> NoReturn:
    """Report an error in the current environment and terminate the action."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error::{message}", file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def set_output(name: str, value: str | Path) -> None:
    """Write a single-line value to the GitHub Actions output file."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    rendered = str(value)
    if "\n" in rendered or "\r" in rendered:
        fail(f"Action output {name!r} unexpectedly contains a newline.")
    with open(output_file, "a", encoding="utf-8") as stream:
        stream.write(f"{name}={rendered}\n")


def parse_boolean(value: str, *, name: str) -> bool:
    """Parse a strict, case-insensitive boolean action input."""
    try:
        return BOOLEAN_VALUES[value.strip().lower()]
    except KeyError:
        fail(f"{name} must be 'true' or 'false', got {value!r}.")


def resolve_path(value: str, *, base: Path) -> Path:
    """Resolve an absolute path, interpreting relative values from a base path."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def validate_target_runner(target: str, runner_os: str) -> None:
    """Validate that a build target is supported on the current runner OS."""
    if target not in TARGET_RUNNERS:
        choices = ", ".join(TARGET_RUNNERS)
        fail(f"Unsupported target {target!r}. Choose one of: {choices}.")
    if runner_os not in TARGET_RUNNERS[target]:
        allowed = ", ".join(sorted(TARGET_RUNNERS[target]))
        fail(
            f"Target {target!r} cannot be built on {runner_os or 'this runner'}. "
            f"Use one of: {allowed}."
        )


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command and terminate the action if the command fails."""
    print("+ " + shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture_output,
    )
    if result.returncode != 0:
        if capture_output:
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def resolve_output_path(working_directory: Path, target: str) -> Path:
    """Resolve the configured or default build output directory."""
    configured = os.environ.get("ACTION_OUTPUT_DIRECTORY", "").strip()
    if configured:
        return resolve_path(configured, base=working_directory)
    return (working_directory / "build" / target).resolve()


def prepare() -> None:
    """Validate inputs and expose toolchain metadata for subsequent steps."""
    working_directory = Path.cwd().resolve()
    target = os.environ.get("ACTION_TARGET", "").strip().lower()
    runner_os = os.environ.get("RUNNER_OS", "")

    validate_target_runner(target, runner_os)
    if not (working_directory / "pyproject.toml").is_file():
        fail(
            f"No pyproject.toml found in {working_directory}. Check the "
            "working-directory input. Requirements-only projects are not yet "
            "supported by this prototype."
        )

    version_result = run_checked(
        ["flet", "--version", "--json"],
        cwd=working_directory,
        capture_output=True,
    )
    try:
        version_info = json.loads(version_result.stdout)
        flet_version = str(version_info["flet"])
        flutter_version = str(version_info["flutter"])
        linux_dependencies = list(version_info["linux_dependencies"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        fail(f"Could not parse `flet --version --json` output: {error}.")

    should_install_linux_dependencies = parse_boolean(
        os.environ.get("ACTION_INSTALL_LINUX_DEPENDENCIES", "true"),
        name="install-linux-dependencies",
    )
    install_linux_dependencies = target == "linux" and should_install_linux_dependencies

    runner_temp = Path(os.environ.get("RUNNER_TEMP", working_directory / "build"))
    dependencies_file = runner_temp / "flet-linux-build-dependencies.txt"
    dependencies_file.parent.mkdir(parents=True, exist_ok=True)
    dependencies_file.write_text(
        "".join(f"{dependency}\n" for dependency in linux_dependencies),
        encoding="utf-8",
    )

    output_path = resolve_output_path(working_directory, target)
    set_output("working-directory", working_directory)
    set_output("output-path", output_path)
    set_output("flet-version", flet_version)
    set_output("flutter-version", flutter_version)
    set_output(
        "install-linux-dependencies",
        str(install_linux_dependencies).lower(),
    )
    set_output("linux-dependencies-file", dependencies_file)

    print(f"Flet {flet_version} requires Flutter {flutter_version}.")
    print(f"Building {target} on {runner_os}; output: {output_path}")


def parse_extra_args(value: str) -> list[str]:
    """Parse additional Flet arguments while rejecting managed options."""
    try:
        arguments = shlex.split(value, posix=True)
    except ValueError as error:
        fail(f"Could not parse extra-args: {error}.")

    reserved = {
        "-o": "output-directory",
        "--output": "output-directory",
        "--python-version": "bundled-python-version",
        "--build-number": "build-number",
        "--build-version": "build-version",
    }
    for argument in arguments:
        option = argument.split("=", 1)[0]
        if option in reserved:
            fail(
                f"Pass {option} through the {reserved[option]} Action input, "
                "not extra-args."
            )
    return arguments


def create_build_command(target: str, output_path: Path) -> list[str]:
    """Create the Flet build command from action inputs."""
    command = [
        "flet",
        "build",
        target,
        "--yes",
        "--verbose",
        "--output",
        str(output_path),
    ]

    optional_inputs = (
        ("ACTION_BUNDLED_PYTHON_VERSION", "--python-version"),
        ("ACTION_BUILD_NUMBER", "--build-number"),
        ("ACTION_BUILD_VERSION", "--build-version"),
    )
    for environment_name, option in optional_inputs:
        value = os.environ.get(environment_name, "").strip()
        if value:
            command.extend([option, value])

    command.extend(parse_extra_args(os.environ.get("ACTION_EXTRA_ARGS", "")))
    return command


def build() -> None:
    """Run the configured Flet build and verify that it produced output."""
    working_directory = Path.cwd().resolve()
    target = os.environ.get("ACTION_TARGET", "").strip().lower()
    output_path = resolve_path(
        os.environ.get("ACTION_OUTPUT_PATH", ""), base=working_directory
    )
    command = create_build_command(target, output_path)

    run_checked(command, cwd=working_directory)
    if not output_path.is_dir() or not any(output_path.iterdir()):
        fail(f"Flet completed without producing files in {output_path}.")

    set_output("output-path", output_path)


def zip_directory(source: Path, destination: Path) -> None:
    """Create a ZIP archive containing a directory and its files."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(
                    path, arcname=Path(source.name) / path.relative_to(source)
                )


def zip_files(sources: list[Path], destination: Path) -> None:
    """Create a ZIP archive containing files at its top level."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(sources):
            archive.write(path, arcname=path.name)


def tar_directory(source: Path, destination: Path) -> None:
    """Create a compressed tar archive while preserving filesystem metadata."""
    with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        archive.add(source, arcname=source.name, recursive=True)


def zip_apple_bundle(source: Path, destination: Path) -> None:
    """Archive an Apple bundle while preserving its resource metadata."""
    ditto = shutil.which("ditto")
    if ditto:
        run_checked(
            [
                ditto,
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(source),
                str(destination),
            ],
            cwd=source.parent,
        )
    else:
        zip_directory(source, destination)


def find_mobile_artifacts(source: Path, suffix: str) -> list[Path]:
    """Find mobile build artifacts and their accompanying checksums."""
    matching = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and (path.name.endswith(suffix) or path.name.endswith(f"{suffix}.sha1"))
    )
    primary = [path for path in matching if path.name.endswith(suffix)]
    if not primary:
        fail(f"No {suffix} artifact was found in {source}.")
    return matching


def archive_output() -> None:
    """Create a single portable archive from the build output."""
    working_directory = Path.cwd().resolve()
    target = os.environ.get("ACTION_TARGET", "").strip().lower()
    output_path = resolve_path(
        os.environ.get("ACTION_OUTPUT_PATH", ""), base=working_directory
    )
    should_archive = parse_boolean(
        os.environ.get("ACTION_ARCHIVE_OUTPUT", "true"),
        name="archive-output",
    )

    if not output_path.is_dir():
        fail(f"Build output directory does not exist: {output_path}.")
    if not should_archive:
        set_output("archive-path", "")
        write_summary(target, output_path, None)
        return

    runner_temp = Path(os.environ.get("RUNNER_TEMP", working_directory / "build"))
    archive_root = runner_temp / "flet-build-action-archives" / target
    shutil.rmtree(archive_root, ignore_errors=True)
    archive_root.mkdir(parents=True, exist_ok=True)

    if target in {"apk", "aab"}:
        archive_path = archive_root / f"flet-{target}.zip"
        zip_files(find_mobile_artifacts(output_path, f".{target}"), archive_path)
    elif target == "ipa":
        ipa_files = sorted(output_path.rglob("*.ipa"))
        archive_path = archive_root / "flet-ipa.zip"
        if ipa_files:
            zip_files(ipa_files, archive_path)
        else:
            archives = sorted(output_path.rglob("*.xcarchive"))
            if not archives:
                fail(f"No .ipa or .xcarchive artifact was found in {output_path}.")
            zip_apple_bundle(archives[0], archive_path)
    elif target in {"macos", "ios-simulator"}:
        bundles = sorted(output_path.rglob("*.app"))
        if not bundles:
            fail(f"No .app bundle was found in {output_path}.")
        archive_path = archive_root / f"flet-{target}.zip"
        zip_apple_bundle(bundles[0], archive_path)
    elif target == "linux":
        archive_path = archive_root / "flet-linux.tar.gz"
        tar_directory(output_path, archive_path)
    elif target in {"web", "windows"}:
        archive_path = archive_root / f"flet-{target}.zip"
        zip_directory(output_path, archive_path)
    else:
        fail(f"Output archiving is not implemented for target {target!r}.")

    set_output("archive-path", archive_path.resolve())
    write_summary(target, output_path, archive_path)


def write_summary(
    target: str,
    output_path: Path,
    archive_path: Path | None,
) -> None:
    """Append build and archive details to the GitHub step summary."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    with open(summary_file, "a", encoding="utf-8") as stream:
        stream.write("## Flet build\n\n")
        stream.write(f"- Target: `{target}`\n")
        stream.write(
            f"- Toolchain: Flet `{os.environ.get('ACTION_FLET_VERSION', 'unknown')}`, "
            f"Flutter `{os.environ.get('ACTION_FLUTTER_VERSION', 'unknown')}`\n"
        )
        stream.write(f"- Raw output: `{output_path}`\n")
        stream.write(f"- Archive: `{archive_path if archive_path else 'disabled'}`\n")


def main() -> None:
    """Dispatch the requested action lifecycle command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "build", "archive"))
    options = parser.parse_args()

    if options.command == "prepare":
        prepare()
    elif options.command == "build":
        build()
    else:
        archive_output()


if __name__ == "__main__":
    main()
