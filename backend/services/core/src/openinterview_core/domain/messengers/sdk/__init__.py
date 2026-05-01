"""Messenger SDK — stable plugin contract and channel-agnostic primitives.

Plugins import only from this package. The kernel and registry depend
only on this package. Adding a new messenger means:

  1. Create `plugins/<channel>/`.
  2. Drop a `plugin.json` manifest matching `manifest.MessengerManifest`.
  3. Implement `MessengerPlugin` in a runtime module.
  4. Export an `entry` callable returning the constructed plugin.
"""
