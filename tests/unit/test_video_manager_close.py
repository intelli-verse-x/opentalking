"""Every owned job gets a cleanup attempt despite an earlier failure."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "source_path,class_name,operation",
    [
        ("opentalking/video_creation_jobs.py", "VideoCreationJobManager", "stop"),
        ("opentalking/streaming/rtmps_jobs.py", "ChunkedRTMPSJobManager", "delete"),
    ],
)
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
def test_actual_manager_close_attempts_all_owned_jobs(source_path, class_name, operation, failure):
    source = Path(__file__).parents[2] / source_path
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "close")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    namespace = {}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])),
            str(source),
            "exec",
        ),
        namespace,
    )
    calls = []

    async def stop_or_delete(job_id):
        calls.append(job_id)
        if job_id == "first" and failure is not None:
            raise failure("synthetic")
        if job_id == "disappeared":
            raise KeyError(job_id)

    manager = SimpleNamespace(jobs=dict.fromkeys(["first", "second", "disappeared"]))
    setattr(manager, operation, stop_or_delete)
    if failure is None:
        asyncio.run(namespace["close"](manager))
    else:
        with pytest.raises(failure):
            asyncio.run(namespace["close"](manager))
    assert calls == ["first", "second", "disappeared"]
