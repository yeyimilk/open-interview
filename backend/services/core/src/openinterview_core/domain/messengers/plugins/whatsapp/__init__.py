"""WhatsApp messenger plugin (Baileys bridge backend)."""
from .pairing import WhatsAppPairingTracker
from .runtime import BridgePairOut, WhatsAppPlugin, build_plugin

__all__ = [
    "WhatsAppPlugin",
    "build_plugin",
    "BridgePairOut",
    "WhatsAppPairingTracker",
]
