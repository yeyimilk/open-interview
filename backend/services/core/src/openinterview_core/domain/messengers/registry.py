"""Discover plugins on disk, load their manifests, and instantiate them.

Layout convention:

    plugins/
      <plugin_id>/
        plugin.json          MessengerManifest
        ... whatever the plugin needs ...

The manifest's `entry` is a `module:attr` reference. `attr` may be:

  * a `MessengerPlugin` instance
  * a zero-arg callable returning a `MessengerPlugin`
  * a callable accepting `**config` returning a `MessengerPlugin`

`config` (optional) is read from the application Settings under
`messenger_plugin_configs[plugin_id]` and validated by the manifest's
`config_schema` if you bring one.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from openinterview_logging import get_logger

from .sdk.manifest import MessengerManifest, load_manifest
from .sdk.plugin import MessengerPlugin

log = get_logger(__name__)


def _resolve_entry(entry: str) -> Any:
    if ":" not in entry:
        raise ValueError(f"manifest entry must be 'module:attr', got {entry!r}")
    module_path, attr = entry.split(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _instantiate(target: Any, config: dict[str, Any]) -> MessengerPlugin:
    if callable(target):
        try:
            return target(**config) if config else target()
        except TypeError:
            return target()
    return target


def discover_manifests(root: Path) -> list[tuple[Path, MessengerManifest]]:
    if not root.exists():
        return []
    out: list[tuple[Path, MessengerManifest]] = []
    for item in sorted(root.iterdir()):
        manifest_path = item / "plugin.json"
        if item.is_dir() and manifest_path.exists():
            try:
                out.append((manifest_path, load_manifest(manifest_path)))
            except Exception as e:  # pragma: no cover - logged for ops
                log.error("messenger_manifest_invalid", path=str(manifest_path), error=str(e))
    return out


class PluginRegistry:
    """Holds the live `(manifest, plugin)` map keyed by plugin id."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[MessengerManifest, MessengerPlugin]] = {}

    def register(self, manifest: MessengerManifest, plugin: MessengerPlugin) -> None:
        self._items[manifest.id] = (manifest, plugin)

    def get(self, plugin_id: str) -> tuple[MessengerManifest, MessengerPlugin] | None:
        return self._items.get(plugin_id)

    def all(self) -> list[tuple[MessengerManifest, MessengerPlugin]]:
        return list(self._items.values())


def build_registry(
    root: Path,
    *,
    config_provider: Callable[[str], dict[str, Any]] | None = None,
) -> PluginRegistry:
    """Walk `root` for manifests, instantiate every plugin, return a registry."""
    reg = PluginRegistry()
    for manifest_path, manifest in discover_manifests(root):
        try:
            target = _resolve_entry(manifest.entry)
            cfg = config_provider(manifest.id) if config_provider else {}
            plugin = _instantiate(target, cfg or {})
            reg.register(manifest, plugin)
            log.info("messenger_plugin_loaded", id=manifest.id, name=manifest.name)
        except Exception as e:  # pragma: no cover - logged for ops
            log.error(
                "messenger_plugin_load_failed",
                id=manifest.id,
                path=str(manifest_path),
                error=str(e),
            )
    return reg
