from __future__ import annotations

import importlib.util
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "flet_action.py"
SPEC = importlib.util.spec_from_file_location("flet_action", MODULE_PATH)
assert SPEC and SPEC.loader
flet_action = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flet_action)


class ActionValidationTests(unittest.TestCase):
    """Validate action input handling before a build starts."""

    def test_accepts_supported_runner(self) -> None:
        """Allow targets on runner operating systems that can build them."""
        flet_action.validate_target_runner("apk", "Linux")
        flet_action.validate_target_runner("ios-simulator", "macOS")

    def test_rejects_incompatible_runner(self) -> None:
        """Reject targets on runner operating systems that cannot build them."""
        with self.assertRaises(SystemExit):
            flet_action.validate_target_runner("windows", "Linux")

    def test_parses_extra_args_without_shell_evaluation(self) -> None:
        """Parse quoted extra build arguments without invoking a shell."""
        self.assertEqual(
            flet_action.parse_extra_args('--product "My App" --no-wasm'),
            ["--product", "My App", "--no-wasm"],
        )

    def test_rejects_reserved_extra_arg(self) -> None:
        """Require managed build options to use their dedicated action inputs."""
        with self.assertRaises(SystemExit):
            flet_action.parse_extra_args("--output=dist")

    def test_build_command_uses_dedicated_inputs(self) -> None:
        """Translate dedicated action inputs into managed Flet CLI arguments."""
        environment = {
            "ACTION_BUNDLED_PYTHON_VERSION": "3.13",
            "ACTION_BUILD_NUMBER": "42",
            "ACTION_BUILD_VERSION": "1.2.3",
            "ACTION_EXTRA_ARGS": "--no-wasm",
        }
        with patch.dict(os.environ, environment, clear=False):
            command = flet_action.create_build_command("web", Path("/tmp/web"))

        self.assertEqual(
            command,
            [
                "flet",
                "build",
                "web",
                "--yes",
                "--verbose",
                "--output",
                "/tmp/web",
                "--python-version",
                "3.13",
                "--build-number",
                "42",
                "--build-version",
                "1.2.3",
                "--no-wasm",
            ],
        )


class OutputArchivingTests(unittest.TestCase):
    """Validate archive shapes produced from Flet build output directories."""

    def test_linux_tar_preserves_executable_mode(self) -> None:
        """Preserve executable permissions in Linux tar.gz archives."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "linux"
            source.mkdir()
            executable = source / "app"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            destination = root / "linux.tar.gz"

            flet_action.tar_directory(source, destination)

            with tarfile.open(destination, "r:gz") as archive:
                member = archive.getmember("linux/app")
                self.assertTrue(member.mode & stat.S_IXUSR)

    def test_zip_contains_top_level_output_directory(self) -> None:
        """Include the raw output directory as the top-level ZIP entry."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "web"
            source.mkdir()
            (source / "index.html").write_text("ok", encoding="utf-8")
            destination = root / "web.zip"

            flet_action.zip_directory(source, destination)

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.namelist(), ["web/index.html"])

    def test_android_outputs_are_single_archives(self) -> None:
        """Package Android APK and AAB outputs into one archive per target."""
        cases = {
            "aab": ["app-release.aab"],
            "apk": [
                "app-arm64-v8a.apk",
                "app-arm64-v8a.apk.sha1",
                "app-x86_64.apk",
            ],
        }
        for target, filenames in cases.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / target
                source.mkdir()
                for name in filenames:
                    (source / name).write_text(name, encoding="utf-8")
                output_file = root / "outputs"
                environment = {
                    "ACTION_TARGET": target,
                    "ACTION_OUTPUT_PATH": str(source),
                    "ACTION_ARCHIVE_OUTPUT": "true",
                    "GITHUB_OUTPUT": str(output_file),
                    "RUNNER_TEMP": str(root / "runner"),
                }

                with patch.dict(os.environ, environment, clear=False):
                    flet_action.archive_output()

                archive_path = (
                    root
                    / "runner"
                    / "flet-build-action-archives"
                    / target
                    / f"flet-{target}.zip"
                )
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertEqual(sorted(archive.namelist()), sorted(filenames))
                self.assertEqual(
                    output_file.read_text(encoding="utf-8"),
                    f"archive-path={archive_path.resolve()}\n",
                )

    def test_disabled_archiving_leaves_archive_path_empty(self) -> None:
        """Expose an empty archive path when archive creation is disabled."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "web"
            source.mkdir()
            (source / "index.html").write_text("ok", encoding="utf-8")
            output_file = root / "outputs"
            environment = {
                "ACTION_TARGET": "web",
                "ACTION_OUTPUT_PATH": str(source),
                "ACTION_ARCHIVE_OUTPUT": "false",
                "GITHUB_OUTPUT": str(output_file),
            }

            with patch.dict(os.environ, environment, clear=False):
                flet_action.archive_output()

            self.assertEqual(output_file.read_text(encoding="utf-8"), "archive-path=\n")


if __name__ == "__main__":
    unittest.main()
