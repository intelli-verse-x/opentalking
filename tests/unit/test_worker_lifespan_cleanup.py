"""Actual worker lifespan with inert resources, including orphan controllers."""

from __future__ import annotations

import ast
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid


def _lifespan(calls, failures):
    source = Path(__file__).parents[2] / "opentalking/runtime/server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"
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
        if "consumer" in failures:
            raise RuntimeError("consumer")
        await asyncio.Event().wait()

    runners = {"live": Resource("runner-live"), "other": Resource("runner-other")}
    controllers = {"live": Resource("output-live"), "orphan": Resource("output-orphan")}
    namespace = dict(
        asyncio=asyncio,
        os=os,
        uuid=uuid,
        Path=Path,
        asynccontextmanager=asynccontextmanager,
        redis=SimpleNamespace(from_url=lambda *args, **kwargs: Resource("redis")),
        runners=runners,
        output_controllers=controllers,
        consume_task_queue=consume,
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
    return namespace["lifespan"], runners, controllers


class WorkerLifespanCleanup(unittest.TestCase):
    def run_case(self, failures=(), body_failure=False):
        calls = []
        context, runners, controllers = _lifespan(calls, failures)

        async def scenario():
            async with context(SimpleNamespace(state=SimpleNamespace())):
                await asyncio.sleep(0)
                if body_failure:
                    raise RuntimeError("body")

        if failures or body_failure:
            with self.assertRaises(RuntimeError):
                asyncio.run(scenario())
        else:
            asyncio.run(scenario())
        self.assertEqual(
            calls, ["output-live", "output-orphan", "runner-live", "runner-other", "redis"]
        )
        self.assertEqual(runners, {})
        self.assertEqual(controllers, {})

    def test_normal_includes_snapshot_only_outputs(self):
        self.run_case()

    def test_exception_in_lifespan_body(self):
        self.run_case(body_failure=True)

    def test_consumer_failure(self):
        self.run_case(failures=("consumer",))

    def test_output_failure_still_closes_other_outputs_sources_redis(self):
        self.run_case(failures=("output-live",))

    def test_source_failure_still_closes_other_sources_redis(self):
        self.run_case(failures=("runner-live",))

    def test_multiple_failures_still_attempt_every_resource(self):
        self.run_case(
            failures=("output-live", "output-orphan", "runner-live", "runner-other", "redis")
        )
