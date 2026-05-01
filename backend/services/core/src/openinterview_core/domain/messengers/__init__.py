"""Messengers — pluggable messaging-platform support.

The SDK is in `sdk/`; concrete plugins live under `plugins/<id>/`. The
kernel and registry never import a plugin module directly — plugins are
discovered via their `plugin.json` manifest and entry-point string.
"""
from __future__ import annotations

from .sdk.kernel import MessengerKernel
from .sdk.plugin import MessengerCapabilities, MessengerPlugin
from .sdk.types import (
    Attachment,
    InboundTurn,
    OutboundReply,
)

__all__ = [
    "MessengerKernel",
    "MessengerPlugin",
    "MessengerCapabilities",
    "InboundTurn",
    "Attachment",
    "OutboundReply",
]
