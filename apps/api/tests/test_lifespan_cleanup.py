"""Exercise the actual lifespan body with inert resources and no app imports."""
import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest


def lifespan_body(calls, failing_close=None):
    source = Path(__file__).parents[1] / "main.py"
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    class Resource:
        def __init__(self, name):
            self.name = name
        async def close(self):
            calls.append(self.name)
            if self.name == failing_close:
                raise RuntimeError("synthetic close failure")
        async def aclose(self):
            await self.close()
    settings = SimpleNamespace(streaming_enabled=False, redis_url="inert-not-a-real-endpoint")
    namespace = {
        "asynccontextmanager": asynccontextmanager,
        "init_voice_store": lambda: None,
        "get_settings": lambda: settings,
        "VideoCreationJobManager": lambda _: Resource("source"),
        "ChunkedRTMPSJobManager": lambda *_: Resource("publisher"),
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="synthetic-boot")),
        "redis": SimpleNamespace(from_url=lambda *_args, **_kw: Resource("redis")),
    }
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["lifespan"]


class LifespanCleanup(unittest.TestCase):
    def run_case(self, failing_close=None, body_failure=False):
        calls = []
        context = lifespan_body(calls, failing_close)
        async def scenario():
            async with context(SimpleNamespace(state=SimpleNamespace())):
                if body_failure:
                    raise RuntimeError("synthetic application failure")
        if failing_close or body_failure:
            with self.assertRaises(RuntimeError):
                asyncio.run(scenario())
        else:
            asyncio.run(scenario())
        self.assertEqual(calls, ["publisher", "source", "redis"])

    def test_normal_shutdown(self):
        self.run_case()

    def test_application_exception_still_closes_every_resource(self):
        self.run_case(body_failure=True)

    def test_publisher_close_failure_still_closes_source_and_redis(self):
        self.run_case(failing_close="publisher")

    def test_source_close_failure_still_closes_redis(self):
        self.run_case(failing_close="source")

    def test_redis_failure_preserves_all_prior_close_attempts(self):
        self.run_case(failing_close="redis")
