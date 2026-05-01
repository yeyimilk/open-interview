import { describe, expect, it, vi } from "vitest";
import { EventEmitter } from "node:events";

import { AccountManager } from "../src/manager.js";
import type { Config } from "../src/config.js";
import type { SocketDriver } from "../src/types.js";
import type { Webhook } from "../src/webhook.js";

class FakeDriver implements SocketDriver {
  private em = new EventEmitter();
  public sent: { jid: string; text: string }[] = [];
  public loggedOut = false;
  on(e: any, cb: any) {
    this.em.on(e, cb);
  }
  async start() {
    // simulate the QR + paired sequence
    setImmediate(() => this.em.emit("qr", { qr_text: "QR-DATA-XYZ" }));
    setImmediate(() =>
      this.em.emit("paired", {
        jid: "15551112222@s.whatsapp.net",
        phone_number: "15551112222",
      })
    );
  }
  async send(jid: string, text: string) {
    this.sent.push({ jid, text });
  }
  async logout() {
    this.loggedOut = true;
  }
  async listGroups() {
    return [
      { jid: "1-1@g.us", subject: "Friends", participants_count: 3 },
    ];
  }
  async resolveInvite(code: string) {
    return { jid: `${code}@g.us`, subject: "Invited", participants_count: 1 };
  }
  emitMessage(payload: any) {
    this.em.emit("message", payload);
  }
}

class FakeWebhook implements Webhook {
  public posts: { url: string; body: any }[] = [];
  async post(url: string, _secret: string, body: unknown) {
    this.posts.push({ url, body });
  }
}

const cfg: Config = {
  host: "127.0.0.1",
  port: 0,
  dataDir: "/tmp/wa-test",
  serviceToken: "t",
  webhookUrl: "http://core/webhooks/whatsapp/",
  webhookSecret: "s",
};

describe("AccountManager", () => {
  it("emits QR then paired events through the pair session", async () => {
    let driver: FakeDriver | null = null;
    const wh = new FakeWebhook();
    const mgr = new AccountManager(
      cfg,
      (_id) => {
        driver = new FakeDriver();
        return driver;
      },
      wh
    );

    const session = await mgr.startPair();
    expect(session.state).toBe("waiting");

    // Wait until both QR (async png encode) and paired have settled.
    for (let i = 0; i < 20; i++) {
      const u = mgr.getPair(session.pair_id);
      if (u?.state === "paired" && u?.qr_image_b64) break;
      await new Promise((r) => setTimeout(r, 10));
    }

    const updated = mgr.getPair(session.pair_id);
    expect(updated?.state).toBe("paired");
    expect(updated?.phone_number).toBe("15551112222");
    expect(typeof updated?.qr_image_b64).toBe("string");
    expect(updated?.qr_image_b64).toMatch(/^data:image\/png;base64,/);

    // 'paired' webhook posted.
    expect(wh.posts.some((p) => p.body.type === "paired")).toBe(true);
  });

  it("forwards inbound user messages to the webhook", async () => {
    let driver: FakeDriver | null = null;
    const wh = new FakeWebhook();
    const mgr = new AccountManager(
      cfg,
      () => {
        driver = new FakeDriver();
        return driver;
      },
      wh
    );
    await mgr.startPair();
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    driver!.emitMessage({
      jid: "15553334444@s.whatsapp.net",
      phone_number: "15553334444",
      message_id: "WAID-1",
      text: "hello",
      timestamp: 1700000000000,
      is_from_me: false,
    });

    const msgPosts = wh.posts.filter((p) => p.body.type === "message");
    expect(msgPosts.length).toBe(1);
    expect(msgPosts[0]!.body.text).toBe("hello");
    expect(msgPosts[0]!.body.message_id).toBe("WAID-1");
  });

  it("forwards every message the driver emits (driver does its own from-me filtering)", async () => {
    // The driver layer (BaileysDriver) is responsible for dropping
    // outbound echoes while still passing self-chat messages through.
    // The manager just trusts what it receives.
    let driver: FakeDriver | null = null;
    const wh = new FakeWebhook();
    const mgr = new AccountManager(
      cfg,
      () => {
        driver = new FakeDriver();
        return driver;
      },
      wh
    );
    await mgr.startPair();
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    driver!.emitMessage({
      jid: "self@s.whatsapp.net",
      phone_number: "self",
      message_id: "M",
      text: "self",
      timestamp: 0,
      is_from_me: true,
    });
    expect(wh.posts.filter((p) => p.body.type === "message").length).toBe(1);
  });

  it("send() routes to the correct driver", async () => {
    let driver: FakeDriver | null = null;
    const wh = new FakeWebhook();
    const mgr = new AccountManager(
      cfg,
      () => {
        driver = new FakeDriver();
        return driver;
      },
      wh
    );
    const s = await mgr.startPair();
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    await mgr.send(s.account_id, "15559998888@s.whatsapp.net", "hi");
    expect(driver!.sent).toEqual([
      { jid: "15559998888@s.whatsapp.net", text: "hi" },
    ]);
  });

  it("send() rejects when account isn't paired", async () => {
    const mgr = new AccountManager(
      cfg,
      () => new FakeDriver() as SocketDriver,
      { post: vi.fn() } as any as Webhook
    );
    await expect(
      mgr.send("nope", "x@s.whatsapp.net", "hi")
    ).rejects.toThrow(/not connected/);
  });

  it("logout removes the account from listAccounts", async () => {
    let driver: FakeDriver | null = null;
    const mgr = new AccountManager(
      cfg,
      () => {
        driver = new FakeDriver();
        return driver;
      },
      { post: vi.fn() } as any as Webhook
    );
    const s = await mgr.startPair();
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    expect(mgr.listAccounts().some((a) => a.account_id === s.account_id)).toBe(
      true
    );
    await mgr.logout(s.account_id);
    expect(driver!.loggedOut).toBe(true);
    expect(mgr.listAccounts().some((a) => a.account_id === s.account_id)).toBe(
      false
    );
  });
});
