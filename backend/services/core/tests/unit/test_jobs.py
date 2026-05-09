from __future__ import annotations

import pytest

from openinterview_core.infra import jobs


@pytest.mark.asyncio
async def test_enqueue_arq_job_propagates_traceparent(monkeypatch):
    captured: dict = {}

    class FakeRedis:
        async def enqueue_job(self, name, *args, **kwargs):
            captured["name"] = name
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def close(self):
            captured["closed"] = True

    async def fake_create_pool(_settings):
        return FakeRedis()

    monkeypatch.setattr(jobs, "create_pool", fake_create_pool)
    monkeypatch.setattr(
        jobs,
        "current_trace_headers",
        lambda: {"traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"},
    )

    ok = await jobs.enqueue_arq_job("redis://localhost:6379/0", "generate_project_qa", "u")

    assert ok is True
    assert captured["name"] == "generate_project_qa"
    assert captured["args"] == ("u",)
    assert captured["kwargs"]["_traceparent"].startswith("00-")
    assert captured["closed"] is True
