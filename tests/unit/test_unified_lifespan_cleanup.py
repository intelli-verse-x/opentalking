"""Actual unified startup/shutdown with inert resources and no model imports."""

from __future__ import annotations

import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid


def _lifespan(calls, failures):
    source = Path(__file__).parents[2] / "apps/unified/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "unified_lifespan"
    )

    class Resource:
        def __init__(self, name):
            self.name = name

        async def close(self):
            calls.append(self.name)
            if self.name in failures:
                raise RuntimeError(self.name)

        async def aclose(self):
            await self.close()

    async def consume(*args):
        await asyncio.Event().wait()

    async def prewarm():
        if "startup" in failures:
            raise RuntimeError("startup")

    namespace = dict(
        asyncio=asyncio,
        os=SimpleNamespace(environ={}),
        uuid=uuid,
        Path=Path,
        asynccontextmanager=asynccontextmanager,
        init_voice_store=lambda: None,
        get_settings=lambda: SimpleNamespace(),
        VideoCreationJobManager=lambda _: Resource("source"),
        ChunkedRTMPSJobManager=lambda *_: Resource("publisher"),
        InMemoryRedis=lambda: Resource("redis"),
        consume_task_queue=consume,
        log=SimpleNamespace(info=lambda *args: None),
        _prewarm_local_stt_on_startup=prewarm,
    )
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])),
            str(source),
            "exec",
        ),
        namespace,
    )
    return namespace["unified_lifespan"], Resource


class UnifiedLifespanCleanup(unittest.TestCase):
    def run_case(self, failures=(), body_failure=False):
        calls = []
        context, resource = _lifespan(calls, failures)
        app = SimpleNamespace(state=SimpleNamespace())

        async def scenario():
            async with context(app):
                app.state.session_runners["synthetic"] = resource("runner")
                if body_failure:
                    raise RuntimeError("body")

        if failures or body_failure:
            with self.assertRaises(RuntimeError):
                asyncio.run(scenario())
        else:
            asyncio.run(scenario())
        expected = (
            ["publisher", "source", "redis"]
            if "startup" in failures
            else ["publisher", "source", "runner", "redis"]
        )
        self.assertEqual(calls, expected)
        self.assertEqual(app.state.session_runners, {})

    def test_normal_order(self):
        self.run_case()

    def test_startup_prewarm_failure_closes_already_owned_resources(self):
        self.run_case(failures=("startup",))

    def test_body_failure(self):
        self.run_case(body_failure=True)

    def test_publisher_failure(self):
        self.run_case(failures=("publisher",))

    def test_source_failure(self):
        self.run_case(failures=("source",))

    def test_runner_failure(self):
        self.run_case(failures=("runner",))

    def test_multiple_failures_still_close_every_resource(self):
        self.run_case(failures=("publisher", "source", "runner", "redis"))
