"""Exercise the actual private-file writer without generating credentials."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def _writer():
    source = Path(__file__).parents[2] / "scripts/streaming/prepare_mediamtx_harness.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_write_private"
    )
    namespace = dict(os=os, Path=Path, tempfile=tempfile)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])),
            str(source),
            "exec",
        ),
        namespace,
    )
    return namespace["_write_private"], namespace


@unittest.skipUnless(os.name == "posix", "the local harness explicitly requires POSIX")
class HarnessPrivateFiles(unittest.TestCase):
    def test_existing_public_file_is_replaced_by_private_file(self):
        writer, _ = _writer()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "credentials.env"
            target.write_text("old", encoding="utf-8")
            target.chmod(0o644)
            original_fdopen = os.fdopen
            checked = []

            def private_before_write(fd, *args, **kwargs):
                self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
                self.assertEqual(target.read_text(), "old")
                checked.append(True)
                return original_fdopen(fd, *args, **kwargs)

            with patch.object(os, "fdopen", side_effect=private_before_write):
                writer(target, "synthetic-not-a-secret")
            self.assertEqual(checked, [True])
            self.assertEqual(target.read_text(), "synthetic-not-a-secret")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_symlink_target_is_never_modified(self):
        writer, _ = _writer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "unrelated"
            unrelated.write_text("keep", encoding="utf-8")
            target = root / "credentials.env"
            target.symlink_to(unrelated)
            writer(target, "synthetic")
            self.assertEqual(unrelated.read_text(), "keep")
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_text(), "synthetic")

    def test_replace_failure_preserves_old_file_and_removes_temporary(self):
        writer, _ = _writer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "credentials.env"
            target.write_text("keep", encoding="utf-8")
            with patch.object(os, "replace", side_effect=OSError("synthetic")):
                with self.assertRaises(OSError):
                    writer(target, "synthetic")
            self.assertEqual(target.read_text(), "keep")
            self.assertEqual(list(root.iterdir()), [target])

    def test_non_posix_is_refused_before_any_secret_file(self):
        writer, namespace = _writer()
        namespace["os"] = SimpleNamespace(name="nt")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "credentials.env"
            with self.assertRaises(RuntimeError):
                writer(target, "synthetic")
            self.assertFalse(target.exists())
