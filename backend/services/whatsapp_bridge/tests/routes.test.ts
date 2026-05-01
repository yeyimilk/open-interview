import Fastify from "fastify";
import { describe, expect, it } from "vitest";
import { EventEmitter } from "node:events";

import { AccountManager } from "../src/manager.js";
import { registerRoutes } from "../src/routes.js";
import type { Config } from "../src/config.js";
import type { SocketDriver } from "../src/types.js";

class FakeDriver implements SocketDriver {
  private em = new EventEmitter();
  on(e: any, cb: any) {
    this.em.on(e, cb);
  }
  async start() {
    setImmediate(() => this.em.emit("qr", { qr_text: "Q" }));
    setImmediate(() =>
      this.em.emit("paired", {
        jid: "1@s.whatsapp.net",
        phone_number: "1",
      })
    );
  }
  async send() {}
  async logout() {}
  async listGroups() {
    return [{ jid: "1-1@g.us", subject: "G", participants_count: 2 }];
  }
  async resolveInvite(code: string) {
    return { jid: `${code}@g.us`, subject: "Invited", participants_count: 1 };
  }
}

const cfg: Config = {
  host: "127.0.0.1",
  port: 0,
  dataDir: "/tmp/wa-test-routes",
  serviceToken: "tok",
  webhookUrl: "http://core/",
  webhookSecret: "s",
};

function buildApp() {
  const mgr = new AccountManager(
    cfg,
    () => new FakeDriver(),
    { post: async () => {} }
  );
  const app = Fastify();
  registerRoutes(app, { config: cfg, manager: mgr });
  return app;
}

describe("routes", () => {
  it("rejects unauthenticated requests", async () => {
    const app = buildApp();
    const r = await app.inject({ method: "POST", url: "/pair" });
    expect(r.statusCode).toBe(401);
  });

  it("/health is open", async () => {
    const app = buildApp();
    const r = await app.inject({ method: "GET", url: "/health" });
    expect(r.statusCode).toBe(200);
  });

  it("happy-path: pair → status flips to paired → send works", async () => {
    const app = buildApp();
    const headers = { authorization: "Bearer tok" };

    const start = await app.inject({ method: "POST", url: "/pair", headers });
    expect(start.statusCode).toBe(200);
    const session = start.json() as any;

    // Allow QR + paired emissions to fire.
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    const status = await app.inject({
      method: "GET",
      url: `/pair/${session.pair_id}/status`,
      headers,
    });
    expect(status.statusCode).toBe(200);
    expect((status.json() as any).state).toBe("paired");

    const send = await app.inject({
      method: "POST",
      url: "/send",
      headers,
      payload: {
        account_id: session.account_id,
        to_jid: "1@s.whatsapp.net",
        text: "hi",
      },
    });
    expect(send.statusCode).toBe(200);
  });

  it("rejects /send with missing fields", async () => {
    const app = buildApp();
    const r = await app.inject({
      method: "POST",
      url: "/send",
      headers: { authorization: "Bearer tok" },
      payload: { text: "hi" },
    });
    expect(r.statusCode).toBe(400);
  });

  it("lists groups for a paired account", async () => {
    const app = buildApp();
    const headers = { authorization: "Bearer tok" };
    const start = (await app.inject({
      method: "POST",
      url: "/pair",
      headers,
    })).json() as any;
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const res = await app.inject({
      method: "GET",
      url: `/accounts/${start.account_id}/groups`,
      headers,
    });
    expect(res.statusCode).toBe(200);
    expect((res.json() as any).groups[0].subject).toBe("G");
  });

  it("resolves a group invite from a full chat.whatsapp.com URL", async () => {
    const app = buildApp();
    const headers = { authorization: "Bearer tok" };
    const start = (await app.inject({
      method: "POST",
      url: "/pair",
      headers,
    })).json() as any;
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const res = await app.inject({
      method: "POST",
      url: `/accounts/${start.account_id}/group-by-invite`,
      headers,
      payload: { code: "https://chat.whatsapp.com/ABC123XYZ" },
    });
    expect(res.statusCode).toBe(200);
    expect((res.json() as any).group.jid).toBe("ABC123XYZ@g.us");
  });

  it("400s on missing invite code", async () => {
    const app = buildApp();
    const headers = { authorization: "Bearer tok" };
    const start = (await app.inject({
      method: "POST",
      url: "/pair",
      headers,
    })).json() as any;
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const res = await app.inject({
      method: "POST",
      url: `/accounts/${start.account_id}/group-by-invite`,
      headers,
      payload: { code: "" },
    });
    expect(res.statusCode).toBe(400);
  });
});
