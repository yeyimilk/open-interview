// Centralized config — all knobs come from env vars.
import { resolve } from "node:path";

export interface Config {
  host: string;
  port: number;
  dataDir: string;
  serviceToken: string; // shared secret for /pair, /send, etc.
  webhookUrl: string; // where inbound messages are POSTed
  webhookSecret: string; // HMAC for outbound webhook
  otelEnabled: boolean;
  otelServiceName: string;
  otelExporterOtlpEndpoint?: string;
  otelSampleRatio: number;
}

export function loadConfig(): Config {
  return {
    host: process.env.WHATSAPP_BRIDGE_HOST ?? "127.0.0.1",
    port: Number(process.env.WHATSAPP_BRIDGE_PORT ?? "9300"),
    dataDir: resolve(
      process.env.WHATSAPP_BRIDGE_DATA_DIR ?? "./data/whatsapp"
    ),
    serviceToken: process.env.WHATSAPP_BRIDGE_TOKEN ?? "dev-bridge-token",
    webhookUrl:
      process.env.WHATSAPP_BRIDGE_WEBHOOK_URL ??
      "http://127.0.0.1:8000/webhooks/whatsapp/",
    webhookSecret:
      process.env.WHATSAPP_BRIDGE_WEBHOOK_SECRET ?? "dev-webhook-secret",
    otelEnabled: (process.env.OTEL_ENABLED ?? "false").toLowerCase() === "true",
    otelServiceName:
      process.env.OTEL_SERVICE_NAME ?? "openinterview-whatsapp-bridge",
    otelExporterOtlpEndpoint:
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT || undefined,
    otelSampleRatio: Number(process.env.OTEL_SAMPLE_RATIO ?? "1"),
  };
}
