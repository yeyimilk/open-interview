"""Manifest schema shared by every plugin's `plugin.json`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CapabilityManifest(BaseModel):
    streaming: bool = False
    max_outbound_chars: int = 4000
    inbound_voice: bool = False
    inbound_image: bool = False
    rich_buttons: bool = False
    ack_window_s: int = 20
    pair_link_scheme: str = "url"
    supports_typing: bool = False


class ActivationManifest(BaseModel):
    on_startup: bool = False


class MessengerManifest(BaseModel):
    """Declarative description of a plugin. Every plugin folder must contain
    a `plugin.json` matching this schema.
    """

    id: str = Field(..., min_length=1, max_length=64)
    name: str
    description: str = ""
    channels: list[str] = Field(default_factory=list)
    entry: str  # module:attr returning a constructed plugin instance
    config_schema: dict[str, Any] = Field(default_factory=dict)
    capabilities: CapabilityManifest = Field(default_factory=CapabilityManifest)
    activation: ActivationManifest = Field(default_factory=ActivationManifest)


def load_manifest(path: Path) -> MessengerManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return MessengerManifest.model_validate(raw)
