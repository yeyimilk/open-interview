"""Plugin discovery + manifest validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openinterview_core.domain.messengers.registry import (
    build_registry,
    discover_manifests,
)
from openinterview_core.domain.messengers.sdk.manifest import (
    MessengerManifest,
    load_manifest,
)


def test_whatsapp_manifest_discovered():
    root = Path(__file__).resolve().parents[2] / (
        "src/openinterview_core/domain/messengers/plugins"
    )
    manifests = discover_manifests(root)
    ids = [m.id for _, m in manifests]
    assert "whatsapp" in ids


def test_invalid_manifest_skipped(tmp_path: Path):
    pdir = tmp_path / "broken"
    pdir.mkdir()
    (pdir / "plugin.json").write_text("{not json")
    out = discover_manifests(tmp_path)
    assert out == []


def test_load_manifest_validates(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({
        "id": "x", "name": "X", "channels": ["x"],
        "entry": "some.module:plugin",
    }))
    m = load_manifest(p)
    assert isinstance(m, MessengerManifest)
    assert m.capabilities.max_outbound_chars == 4000  # default


def test_build_registry_skips_failing_entries(tmp_path: Path, caplog):
    pdir = tmp_path / "fake"
    pdir.mkdir()
    (pdir / "plugin.json").write_text(json.dumps({
        "id": "fake", "name": "Fake", "channels": ["fake"],
        "entry": "no_such_module:nope",
    }))
    reg = build_registry(tmp_path)
    assert reg.all() == []  # load failed, but build_registry didn't raise


def test_build_registry_real_whatsapp_loads(monkeypatch):
    # Provide minimal env so build_plugin doesn't fail.
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "X")
    monkeypatch.setenv("WHATSAPP_BOT_PHONE_NUMBER", "1234")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "T")
    root = Path(__file__).resolve().parents[2] / (
        "src/openinterview_core/domain/messengers/plugins"
    )
    reg = build_registry(root)
    item = reg.get("whatsapp")
    assert item is not None
    manifest, plugin = item
    assert manifest.id == "whatsapp"
    assert plugin.identity.id == "whatsapp"
