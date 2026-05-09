import { context, propagation, trace } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { NodeSDK } from "@opentelemetry/sdk-node";
import { TraceIdRatioBasedSampler } from "@opentelemetry/sdk-trace-base";

import type { Config } from "./config.js";

let configured = false;
let sdk: NodeSDK | null = null;

export function configureTracing(config: Config): void {
  if (configured || !config.otelEnabled) return;
  const exporter = config.otelExporterOtlpEndpoint
    ? new OTLPTraceExporter({ url: config.otelExporterOtlpEndpoint })
    : undefined;
  sdk = new NodeSDK({
    serviceName: config.otelServiceName,
    traceExporter: exporter,
    sampler: new TraceIdRatioBasedSampler(
      Math.max(0, Math.min(1, config.otelSampleRatio || 1))
    ),
  });
  sdk.start();
  configured = true;
}

export function currentTraceHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  propagation.inject(context.active(), headers);
  return headers;
}

export function tracer() {
  return trace.getTracer("openinterview-whatsapp-bridge");
}

export async function shutdownTracing(): Promise<void> {
  if (!sdk) return;
  await sdk.shutdown();
}
