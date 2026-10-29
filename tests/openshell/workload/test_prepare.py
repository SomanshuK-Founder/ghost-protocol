"""Static build checks only: the workload binary must never execute here."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare


class PreparationTests(unittest.TestCase):
    def build(self, directory: str) -> dict:
        root = Path(directory)
        source = Path(__file__).parent
        for name in ("probe.s", "Dockerfile"):
            shutil.copyfile(source / name, root / name)
        actual_run = prepare.run

        def guarded_run(*args: str) -> str:
            self.assertIn(args[0], ("as", "ld", "readelf", "objdump"))
            return actual_run(*args)

        with patch.object(prepare, "__file__", str(root / "prepare.py")):
            with (
                patch.object(prepare, "run", guarded_run),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                prepare.prepare()
        return json.loads((root / "build/context/inventory.json").read_text())

    def test_reproducible_static_rootfs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-probe-static-") as a:
            with tempfile.TemporaryDirectory(prefix="ghost-probe-static-") as b:
                first, second = self.build(a), self.build(b)
        self.assertEqual(first, second)
        files = {item["path"]: item for item in first["files"]}
        self.assertEqual(len(files), 15)
        self.assertEqual(files["/tmp/ghost-probe"]["mode"], "0o700")
        self.assertEqual(files["/tmp/ghost-probe"]["uid"], 1000)
        self.assertEqual(files["/opt/ghost-probe/probe"]["mode"], "0o555")
        self.assertEqual({x["type"] for x in files.values()}, {"file", "directory"})

    def test_existing_context_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-probe-static-") as directory:
            self.build(directory)
            sentinel = Path(directory) / "build/context/unrelated"
            sentinel.write_text("preserve")
            with self.assertRaises(FileExistsError):
                self.build(directory)
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_wrong_platform_fails_before_build(self) -> None:
        with patch.object(prepare.platform, "machine", return_value="aarch64"):
            with patch.object(prepare, "run") as run:
                with self.assertRaises(SystemExit):
                    prepare.prepare()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
