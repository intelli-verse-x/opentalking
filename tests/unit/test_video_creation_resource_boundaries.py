"""Execute reviewed actual manager/route/method bodies with inert dependencies.
No app/model/media/network imports. Synthetic temporary audio is not decoded.
"""

import ast
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping
import asyncio
import uuid
import tempfile
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

BASE = Path(__file__).parents[2]
FUTURE = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)


def load(path, nodes, env):
    mod = ast.Module(body=[FUTURE, *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), str(path), "exec"), env)


class HTTPException(Exception):
    def __init__(self, **kw):
        self.status_code = kw.get("status_code")


class ChunkHub:
    def __init__(self, **kw):
        self.closed = False

    async def fail(self, *a):
        self.closed = True

    async def finish(self):
        self.closed = True


p = BASE / "opentalking/video_creation_jobs.py"
tree = ast.parse(p.read_text())
env = dict(
    globals(),
    MediaChunk=object,
    math=math,
    time=time,
    dataclass=dataclass,
    field=field,
    Any=Any,
    Awaitable=Awaitable,
    Callable=Callable,
    Mapping=Mapping,
)
load(p, [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))], env)
Manager = env["VideoCreationJobManager"]


async def manager_cases():
    for schedule in ("before", "gate", "running", "completed", "failed"):
        cleaned = []
        ran = []
        ready = asyncio.Event()

        async def runner(sink):
            ran.append(True)
            ready.set()
            if schedule == "failed":
                raise ValueError("synthetic")
            if schedule == "running":
                await asyncio.Event().wait()
            return {}

        manager = Manager(NS())
        job = await manager.submit(
            source="synthetic",
            metadata={},
            runner=runner,
            wait_for_start=schedule in ("before", "gate"),
            cleanup=lambda: cleaned.append(True),
        )
        if schedule == "gate":
            await asyncio.sleep(0)
        if schedule in ("running", "completed", "failed"):
            await ready.wait()
        if schedule in ("completed", "failed"):
            await job.task
        else:
            await manager.stop(job.job_id)
        assert cleaned == [True] and job.hub.closed, (schedule, cleaned, job.status)
        await manager.stop(job.job_id)
        await manager.delete(job.job_id)
        assert cleaned == [True]
        if schedule in ("before", "gate"):
            assert not ran


async def gate_timeout_case():
    called = []
    cleaned = []

    async def runner(sink):
        called.append(True)
        return {}

    manager = Manager(NS(video_creation_publish_gate_timeout_sec=0.01))
    job = await manager.submit(
        source="synthetic",
        metadata={},
        runner=runner,
        wait_for_start=True,
        cleanup=lambda: cleaned.append(True),
    )
    await job.task
    assert (
        job.status == "failed"
        and job.error_code == "publisher_start_timeout"
        and job.hub.closed
        and (cleaned == [True])
        and (not called)
    )
    await manager.start(job.job_id)
    await asyncio.sleep(0)
    assert not called


async def route_cases():
    p = BASE / "apps/api/routes/video_creation.py"
    tree = ast.parse(p.read_text())
    fn = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_video_creation_job"
        )
    )
    fn.decorator_list = []
    for mode in ("cancel-before-entry", "cancel-at-gate", "submission-fails"):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            emotion = root / "emotion.wav"
            emotion.write_bytes(b"synthetic")
            created = []
            manager = Manager(NS())

            async def save_emotion(file):
                return emotion

            class Service:
                def __init__(self, settings):
                    pass

                async def create_from_audio_file(self, **kw):
                    raise AssertionError("renderer must never run")

            class Upload:
                filename = "synthetic.wav"
                content_type = "audio/wav"

                async def read(self):
                    return b"synthetic bytes"

            def named_temp(**kw):
                result = tempfile.NamedTemporaryFile(dir=root, **kw)
                created.append(Path(result.name))
                return result

            class BrokenManager:
                async def submit(self, **kw):
                    raise RuntimeError("synthetic submit failure")

            def default(value=None, **kw):
                return kw.get("default", value)

            ns = dict(
                HTTPException=HTTPException,
                Path=Path,
                tempfile=NS(NamedTemporaryFile=named_temp),
                Form=default,
                File=default,
                _AUDIO_SOURCES={"upload"},
                _parse_fasterliveportrait_config=lambda *a: None,
                _parse_video_composition_config=lambda *a: None,
                preflight_light2d_video_creation=lambda *a, **kw: None,
                Light2DContractError=type("Light2DContractError", (Exception,), {}),
                _save_indextts_emotion_audio=save_emotion,
                _parse_indextts_config=lambda *a, **kw: None,
                VideoCreationService=Service,
                _audio_max_bytes=lambda s: 1024,
                _video_job_manager=lambda req: BrokenManager()
                if mode == "submission-fails"
                else manager,
            )
            load(p, [fn], ns)
            request = NS(app=NS(state=NS(settings=NS())))
            try:
                await ns["create_video_creation_job"](
                    request,
                    NS(status_code=None),
                    model="synthetic",
                    avatar_id="synthetic",
                    audio_source="upload",
                    execution_mode="async",
                    wait_for_rtmps=True,
                    audio_file=Upload(),
                )
            except HTTPException as exc:
                assert mode == "submission-fails" and exc.status_code == 502
            else:
                job = next(iter(manager.jobs.values()))
                if mode == "cancel-at-gate":
                    await asyncio.sleep(0)
                await manager.stop(job.job_id)
            assert (
                created
                and (not any((path.exists() for path in created)))
                and (not emotion.exists())
            ), mode


async def writer_cases():
    p = BASE / "opentalking/video_creation.py"
    tree = ast.parse(p.read_text())
    klass = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VideoCreationService")
    )
    fn = next(
        (
            n
            for n in klass.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_create_from_pcm"
        )
    )
    writers = []

    class Writer:
        def __init__(self, *a, **kw):
            self.closed = False
            writers.append(self)

        def write(self, *a):
            pass

        def close(self):
            self.closed = True

        def abort(self):
            self.closed = True

    class Emitter:
        def __init__(self, *a, **kw):
            pass

        async def add_frame(self, *a):
            raise asyncio.CancelledError

        async def flush(self):
            pass

    pcm = NS(size=10, reshape=lambda n: pcm)
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        ns = dict(
            uuid=uuid,
            shutil=shutil,
            asyncio=asyncio,
            np=NS(int16=object(), asarray=lambda *a, **kw: pcm),
            _normalize_model=lambda m: m,
            _avatar_dir=lambda *a: root / "avatar",
            _normalize_video_composition_config=lambda *a: {},
            _settings_int=lambda s, k, d: d,
            _settings_path=lambda *a: root,
            _write_wav=lambda *a: None,
            _IncrementalVideoWriter=Writer,
            _VideoChunkEmitter=Emitter,
            _iter_light2d_composed_frames=lambda *a, **kw: iter([object()]),
        )
        load(p, [fn], ns)
        try:
            await ns["_create_from_pcm"](
                NS(settings=NS()),
                model="light2d",
                avatar_id="synthetic",
                pcm=pcm,
                title="synthetic",
                source="upload",
                light2d_renderer=NS(fps=25),
                chunk_sink=object(),
            )
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation lost")
        assert len(writers) == 1 and writers[0].closed
        wc = next(
            (
                n
                for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "_IncrementalVideoWriter"
            )
        )
        load(p, [wc], ns)
        writer = ns["_IncrementalVideoWriter"](root / "never-created.mp4", fps=25)
        releases = []
        writer._writer = NS(release=lambda: releases.append(True))
        writer.abort()
        writer.abort()
        assert releases == [True]
        try:
            writer.close()
        except RuntimeError:
            pass
        else:
            raise AssertionError("zero-frame completion accepted")


async def other_writer_cases():
    p = BASE / "opentalking/video_creation.py"
    tree = ast.parse(p.read_text())
    klass = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VideoCreationService")
    )
    fn = next(
        (
            n
            for n in klass.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_create_from_pcm"
        )
    )

    class PCM:
        size = 1

        def reshape(self, n):
            return self

        def __len__(self):
            return 1

        def __getitem__(self, key):
            return self

    for mode in ("add-cancel", "generate-fails", "close-fails", "flush-cancel"):
        writers = []
        closed = []
        pcm = PCM()

        class Writer:
            def __init__(self, *a, **kw):
                self.closed = False
                writers.append(self)

            def write(self, *a):
                pass

            def close(self):
                self.closed = True

            def abort(self):
                self.closed = True

        class Emitter:
            def __init__(self, *a, **kw):
                pass

            async def add_frame(self, *a):
                if mode == "add-cancel":
                    raise asyncio.CancelledError

            async def flush(self):
                if mode == "flush-cancel":
                    raise asyncio.CancelledError

        class Client:
            fps = 25
            audio_chunk_samples = 1

            async def init_session(self, **kw):
                pass

            async def prewarm(self):
                pass

            async def generate(self, *a):
                if mode == "generate-fails":
                    raise ValueError("synthetic generate")
                return [object()]

            async def close(self):
                closed.append(True)
                if mode == "close-fails":
                    raise ValueError("synthetic close")

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            ns = dict(
                uuid=uuid,
                shutil=shutil,
                asyncio=asyncio,
                np=NS(int16=object(), asarray=lambda *a, **kw: pcm),
                _normalize_model=lambda m: m,
                _avatar_dir=lambda *a: root / "avatar",
                _normalize_video_composition_config=lambda *a: {},
                _settings_int=lambda s, k, d: d,
                _settings_path=lambda *a: root,
                _write_wav=lambda *a: None,
                _IncrementalVideoWriter=Writer,
                _VideoChunkEmitter=Emitter,
                preflight_light2d_video_creation=lambda *a, **kw: None,
                resolve_model_backend=lambda *a: NS(backend="local"),
                log=NS(info=lambda *a: None),
                _audio2video_client=lambda *a, **kw: Client(),
                _fasterliveportrait_preroll_samples=lambda *a: 0,
                _init_session_kwargs=lambda **kw: {},
                _frame_array=lambda f: f,
                _VideoFrameComposer=lambda *a: NS(apply=lambda f: f),
            )
            load(p, [fn], ns)
            try:
                await ns["_create_from_pcm"](
                    NS(settings=NS()),
                    model="synthetic",
                    avatar_id="synthetic",
                    pcm=pcm,
                    title="synthetic",
                    source="upload",
                    chunk_sink=object(),
                )
            except (asyncio.CancelledError, ValueError):
                pass
            else:
                raise AssertionError("expected failure lost")
            assert len(writers) == 1 and writers[0].closed and (closed == [True]), mode
    duo = next(
        (
            n
            for n in klass.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_from_duo_dialog"
        )
    )
    branch = next(
        (
            n
            for n in ast.walk(duo)
            if isinstance(n, ast.If)
            and n.orelse
            and isinstance(n.orelse[0], ast.Assign)
            and isinstance(n.orelse[0].value, ast.Call)
            and (getattr(n.orelse[0].value.func, "id", None) == "_IncrementalVideoWriter")
        )
    )
    wrapper = ast.AsyncFunctionDef(
        name="duo_branch",
        args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=branch.orelse,
        decorator_list=[],
    )
    writers = []
    ns = dict(
        _IncrementalVideoWriter=Writer,
        _VideoChunkEmitter=Emitter,
        video_only=Path("never-created.mp4"),
        fps=25,
        total_pcm=PCM(),
        chunk_sink=object(),
        self=NS(settings=NS()),
        _settings_int=lambda s, k, d: d,
        worker=NS(generate_frames_from_script=lambda script: iter([object()])),
        script={},
        _frame_array=lambda f: f,
        _VideoFrameComposer=lambda *a: NS(apply=lambda f: f),
        normalized_composition_config={},
    )
    mode = "add-cancel"
    load(p, [wrapper], ns)
    try:
        await ns["duo_branch"]()
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("duo cancellation lost")
    assert len(writers) == 1 and writers[0].closed


async def main():
    await manager_cases()
    await gate_timeout_case()
    await route_cases()
    await writer_cases()
    await other_writer_cases()
    print(
        "PASS5 actual manager outcome schedules+bounded publisher-gate timeout;3 actual API upload/emotion schedules;Light2D+duo cancellation;4 remote generation/close/flush failure schedules;abort idempotence/zero-frame validation;no app/model/media/network imports"
    )


def test_actual_resource_boundaries_without_model_media_or_network():
    asyncio.run(main())
