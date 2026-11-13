"""A job owns upload cleanup even before its renderer starts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from opentalking.video_creation_jobs import VideoCreationJobManager


@pytest.mark.parametrize("let_task_start", [False, True])
def test_stop_before_publisher_is_terminal_and_removes_owned_files(tmp_path, let_task_start):
    async def scenario():
        calls = []
        upload = tmp_path / "upload.wav"
        emotion = tmp_path / "emotion.wav"
        upload.write_bytes(b"synthetic audio")
        emotion.write_bytes(b"synthetic emotion")
        cleanup_calls = []

        def cleanup():
            cleanup_calls.append(True)
            upload.unlink()
            emotion.unlink()

        async def runner(sink):
            calls.append(True)
            return {}

        manager = VideoCreationJobManager(SimpleNamespace())
        job = await manager.submit(
            source="synthetic",
            metadata={},
            runner=runner,
            wait_for_start=True,
            cleanup=cleanup,
        )
        if let_task_start:
            await asyncio.sleep(0)
            assert job.status == "waiting_publisher"
        await manager.stop(job.job_id)
        assert job.status == "stopped" and job.error_code == "stopped"
        assert job.hub.closed and job.task.cancelled()
        assert not upload.exists() and not emotion.exists()
        await manager.start(job.job_id)
        await manager.stop(job.job_id)
        await manager.delete(job.job_id)
        await asyncio.sleep(0)
        assert calls == [] and cleanup_calls == [True]

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
def test_runner_cleanup_is_exactly_once_for_every_outcome(outcome):
    async def scenario():
        cleanup_calls = []
        started = asyncio.Event()

        async def runner(sink):
            started.set()
            if outcome == "failed":
                raise ValueError("synthetic failure")
            if outcome == "stopped":
                await asyncio.Event().wait()
            return {"synthetic": True}

        manager = VideoCreationJobManager(SimpleNamespace())
        job = await manager.submit(
            source="synthetic",
            metadata={},
            runner=runner,
            cleanup=lambda: cleanup_calls.append(True),
        )
        await started.wait()
        if outcome == "stopped":
            await manager.stop(job.job_id)
        else:
            await job.task
        assert job.status == outcome and cleanup_calls == [True]
        assert job.hub.closed
        await manager.stop(job.job_id)
        await manager.delete(job.job_id)
        assert cleanup_calls == [True]

    asyncio.run(scenario())


def test_orphaned_publish_gate_expires_without_starting_renderer():
    async def scenario():
        calls = []
        cleanup_calls = []

        async def runner(sink):
            calls.append(True)
            return {}

        manager = VideoCreationJobManager(
            SimpleNamespace(video_creation_publish_gate_timeout_sec=0.01)
        )
        job = await manager.submit(
            source="synthetic",
            metadata={},
            runner=runner,
            wait_for_start=True,
            cleanup=lambda: cleanup_calls.append(True),
        )
        await job.task
        assert job.status == "failed" and job.error_code == "publisher_start_timeout"
        assert job.hub.closed and cleanup_calls == [True] and calls == []
        await manager.start(job.job_id)
        await asyncio.sleep(0)
        assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("raw", [None, "bad", float("nan"), float("inf"), -1, 1e20])
def test_publish_gate_timeout_is_always_finite_positive_bounded(raw):
    manager = VideoCreationJobManager(SimpleNamespace(video_creation_publish_gate_timeout_sec=raw))
    assert 0 < manager._publish_gate_timeout_sec() <= 3600
