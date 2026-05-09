// Entry point. Wires Baileys driver factory + manager + routes and binds
// Fastify to the configured host/port.
import Fastify from "fastify";

import { BaileysDriver } from "./baileys-driver.js";
import { loadConfig } from "./config.js";
import { AccountManager } from "./manager.js";
import { registerRoutes } from "./routes.js";
import { configureTracing, shutdownTracing } from "./tracing.js";
import { HttpWebhook } from "./webhook.js";

export async function buildApp() {
  const config = loadConfig();
  configureTracing(config);
  const manager = new AccountManager(
    config,
    (accountId, dataDir) => new BaileysDriver(accountId, dataDir),
    new HttpWebhook()
  );
  const app = Fastify({ logger: { level: "info" } });
  app.addHook("onClose", async () => {
    await shutdownTracing();
  });
  registerRoutes(app, { config, manager });
  return { app, config, manager };
}

async function main() {
  const { app, config, manager } = await buildApp();
  await app.listen({ host: config.host, port: config.port });
  // Re-attach previously-paired accounts. Done after listen so the HTTP
  // surface is up immediately; restore proceeds in the background.
  manager.restoreFromDisk().catch((e) => {
    console.error("[bridge] restoreFromDisk failed:", e);
  });
}

// Run only when invoked directly (not when imported by tests).
const invokedDirectly =
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith("/server.ts") ||
  process.argv[1]?.endsWith("/server.js");
if (invokedDirectly) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
