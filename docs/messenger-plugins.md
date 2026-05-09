# Messenger Plugins

This guide is for adding a new messenger channel without touching Mentor,
Interviewer, or general chat internals. New channels plug into the messenger
SDK and route all inbound turns through `MessengerKernel`.

## 1. Create the plugin folder

Add a folder under:

```text
backend/services/core/src/openinterview_core/domain/messengers/plugins/<channel>/
```

Required files:

```text
plugin.json
__init__.py
runtime.py
```

`plugin.json` declares the stable manifest:

```json
{
  "id": "example",
  "name": "Example Messenger",
  "description": "Example channel runtime",
  "entry": "openinterview_core.domain.messengers.plugins.example:build_plugin",
  "capabilities": {
    "supports_dms": true,
    "supports_groups": false,
    "supports_attachments": false,
    "max_outbound_chars": 4000
  }
}
```

## 2. Implement the runtime

Implement `MessengerPlugin` from `domain/messengers/sdk/plugin.py`.
The kernel expects these core operations:

- `webhook_router()` returns the FastAPI router for provider webhooks.
- `on_inbound(payload)` parses vendor payloads into `InboundTurn`.
- `send_text(to=..., text=..., idempotency_key=...)` sends outbound text.
- `shutdown()` releases sockets, HTTP clients, or sidecar connections.

Channel-specific pairing is allowed, but keep it inside the plugin runtime.
Persist durable account links through `MessengerLinkStore`; do not add
channel-specific auth rows unless the SDK contract cannot represent them.

## 3. Route inbound turns through the kernel

Every inbound message should follow the same path:

```text
provider webhook -> plugin parser -> MessengerKernel.handle_turn()
```

Do not call Mentor, Interviewer, general chat, or DeliveryGuard directly from
a plugin. The kernel owns link resolution, filters, slash commands, active
session dispatch, idempotency, and outbound safety.

See [inbound-message-lifecycle.svg](./inbound-message-lifecycle.svg) for the
full lifecycle.

## 4. Security checklist

- Verify provider signatures or sidecar HMACs before parsing message content.
- Normalize provider user ids before storing them as `external_id`.
- Use one-shot pair tokens when the provider cannot supply trusted OAuth.
- Never trust group display names for authorization; use stable conversation ids.
- Do not store provider access tokens in plaintext.

## 5. Tests

Add these before enabling a new channel:

- Parser unit tests for each inbound payload variant.
- Signature verification tests, including reject cases.
- Kernel integration with `FakeDriver` covering command dispatch and plain text.
- DeliveryGuard path test proving plugin replies go through `kernel.deliver`.
- Group no-loop regression if the provider echoes bot messages.

The fastest starting point is the WhatsApp plugin and the existing messenger
kernel tests under `backend/services/core/tests/`.
