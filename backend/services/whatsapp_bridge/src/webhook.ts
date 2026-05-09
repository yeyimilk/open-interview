// Outbound webhook poster — posts inbound WhatsApp events to core,
// HMAC-signed so the receiver can verify authenticity.
import { createHmac } from "node:crypto";
import { request as undiciRequest } from "undici";

import { currentTraceHeaders, tracer } from "./tracing.js";

export interface Webhook {
  post(url: string, secret: string, body: unknown): Promise<void>;
}

export class HttpWebhook implements Webhook {
  async post(url: string, secret: string, body: unknown): Promise<void> {
    await tracer().startActiveSpan("bridge.webhook.post", async (span) => {
      const json = JSON.stringify(body);
      const sig = sign(json, secret);
      try {
        await undiciRequest(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-bridge-signature-256": `sha256=${sig}`,
            ...currentTraceHeaders(),
          },
          body: json,
        });
      } catch {
        // Webhook delivery is best-effort. Loss is recoverable on next message.
      } finally {
        span.end();
      }
    });
  }
}

function sign(body: string, secret: string): string {
  return createHmac("sha256", secret).update(body).digest("hex");
}
