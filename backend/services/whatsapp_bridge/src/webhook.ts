// Outbound webhook poster — posts inbound WhatsApp events to core,
// HMAC-signed so the receiver can verify authenticity.
import { createHmac } from "node:crypto";
import { request as undiciRequest } from "undici";

export interface Webhook {
  post(url: string, secret: string, body: unknown): Promise<void>;
}

export class HttpWebhook implements Webhook {
  async post(url: string, secret: string, body: unknown): Promise<void> {
    const json = JSON.stringify(body);
    const sig = sign(json, secret);
    try {
      await undiciRequest(url, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-bridge-signature-256": `sha256=${sig}`,
        },
        body: json,
      });
    } catch {
      // Webhook delivery is best-effort. Loss is recoverable on next message.
    }
  }
}

function sign(body: string, secret: string): string {
  return createHmac("sha256", secret).update(body).digest("hex");
}
