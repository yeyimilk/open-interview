# Operating the WhatsApp Bridge

The WhatsApp bridge is a Node/Fastify sidecar that owns Baileys sockets and
exposes a small HTTP API to Core. Core never imports Baileys directly.

## Local startup

```bash
cd whatsapp-bridge
npm install
npm test
npm run dev
```

Core expects these settings:

```text
WHATSAPP_BRIDGE_URL=http://localhost:9300
WHATSAPP_BRIDGE_TOKEN=<shared bearer token>
WHATSAPP_BRIDGE_WEBHOOK_SECRET=<hmac secret>
```

The bridge health endpoint is:

```text
GET /health
```

Core includes bridge status in:

```text
GET /api/v1/healthz
GET /api/v1/readyz
```

## Pairing and re-pairing

1. Open Settings -> Messaging.
2. Start a WhatsApp pair session.
3. Scan the QR code from WhatsApp.
4. Wait for Core to receive the paired webhook and create a `messenger_links`
   row.

If the UI shows `Re-pair needed`, the link still exists but the bridge has no
live socket for that account. Disconnect and pair again, or restart the bridge
if the socket manager is unhealthy.

## Logs to inspect

Core logs:

- `messenger_plugin_loaded`
- `messenger_inbound`
- `messenger_inbound_dedup_skip`
- `messenger_group_idle_skip`
- `delivery_guard_rate_limited`
- `delivery_guard_repeat_drop`

Bridge logs:

- account socket open/close events
- QR creation and pair status transitions
- inbound webhook delivery status
- outbound send errors

When a session refuses to authenticate, check:

- `WHATSAPP_BRIDGE_TOKEN` matches between Core and bridge.
- `WHATSAPP_BRIDGE_WEBHOOK_SECRET` matches for HMAC verification.
- The bridge can reach Core's webhook URL.
- The account id still maps to the linked WhatsApp JID.
- The pair id belongs to the user trying to poll it.

## Operational notes

- Delivery pacing is controlled by `config/tiers.yaml` under each tier's
  `delivery` block.
- Group messages are ignored unless a linked owner explicitly starts or
  addresses an active messenger session.
- Echo suppression happens in both bridge and Core. Keep both layers enabled.
