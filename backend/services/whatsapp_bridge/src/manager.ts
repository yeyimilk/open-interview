// Owns the lifecycle of pair sessions and live accounts. The HTTP routes
// are thin wrappers over this class.
//
// Account state machine:
//   START_PAIR(account_id) -> driver.start()
//                           -> on "qr"     => session.state = "qr"
//                           -> on "paired" => session.state = "paired",
//                                            account is now live and can send/receive
//                           -> on "closed" => session.state = "failed" (if pre-paired)
//                                            else mark account dead

import { randomUUID } from "node:crypto";
import { readFile, readdir, rm, stat } from "node:fs/promises";
import { resolve } from "node:path";

import QRCode from "qrcode";

import type { Config } from "./config.js";
import type {
  InboundMessage,
  PairSession,
  SocketDriver,
} from "./types.js";
import type { Webhook } from "./webhook.js";

export type DriverFactory = (
  accountId: string,
  dataDir: string
) => SocketDriver;

export class AccountManager {
  private pairs = new Map<string, PairSession>();
  private drivers = new Map<string, SocketDriver>(); // by accountId
  private accounts = new Map<string, { jid: string; phone: string }>();

  constructor(
    private readonly config: Config,
    private readonly driverFactory: DriverFactory,
    private readonly webhook: Webhook
  ) {}

  // ---- pairing ---------------------------------------------------------

  async startPair(): Promise<PairSession> {
    const accountId = randomUUID();
    const driver = this.driverFactory(accountId, this.config.dataDir);
    const session: PairSession = {
      pair_id: randomUUID(),
      account_id: accountId,
      state: "waiting",
      qr_image_b64: null,
      qr_text: null,
      phone_number: null,
      jid: null,
      failure_reason: null,
      created_at: Date.now(),
      updated_at: Date.now(),
    };
    this.pairs.set(session.pair_id, session);
    this._wireDriver(accountId, driver, session);
    await driver.start();
    return session;
  }

  /** Bring previously-paired accounts back online by re-starting their
   * Baileys sockets from the on-disk creds. Called once on bridge boot.
   *
   * Stale directories (no creds.json, or creds.json missing `me.id`) are
   * cleaned up here. Restoring multiple sockets for the same phone would
   * cause them to fight each other and regenerate QRs, so we only restore
   * the most-recently-modified valid dir per phone number.
   */
  async restoreFromDisk(): Promise<void> {
    let entries: string[] = [];
    try {
      entries = await readdir(this.config.dataDir);
    } catch {
      return;
    }

    type Candidate = { accountId: string; phone: string; mtime: number };
    const candidates: Candidate[] = [];

    for (const accountId of entries) {
      const dir = resolve(this.config.dataDir, accountId);
      const credsPath = resolve(dir, "creds.json");
      let mtime = 0;
      try {
        const s = await stat(dir);
        if (!s.isDirectory()) continue;
        mtime = s.mtimeMs;
      } catch {
        continue;
      }
      let phone: string | null = null;
      try {
        const text = await readFile(credsPath, "utf8");
        const data = JSON.parse(text);
        const id: string | undefined = data?.me?.id;
        if (id && typeof id === "string") {
          phone = id.split("@", 1)[0]!.split(":", 1)[0]!;
        }
      } catch {
        // creds.json missing or unreadable — treat as stale.
      }
      if (!phone) {
        // Stale / never-completed pair — wipe so we don't restore again.
        try {
          await rm(dir, { recursive: true, force: true });
          console.log(
            `[bridge] removed stale account dir ${accountId.slice(0, 8)}`
          );
        } catch {
          /* ignore */
        }
        continue;
      }
      candidates.push({ accountId, phone, mtime });
    }

    // Keep only the newest dir per phone; wipe the older duplicates.
    const byPhone = new Map<string, Candidate>();
    for (const c of candidates) {
      const cur = byPhone.get(c.phone);
      if (!cur || c.mtime > cur.mtime) {
        if (cur) {
          await rm(resolve(this.config.dataDir, cur.accountId), {
            recursive: true,
            force: true,
          });
          console.log(
            `[bridge] removed older duplicate ${cur.accountId.slice(0, 8)} for phone ${cur.phone}`
          );
        }
        byPhone.set(c.phone, c);
      } else {
        await rm(resolve(this.config.dataDir, c.accountId), {
          recursive: true,
          force: true,
        });
        console.log(
          `[bridge] removed older duplicate ${c.accountId.slice(0, 8)} for phone ${c.phone}`
        );
      }
    }

    for (const c of byPhone.values()) {
      const driver = this.driverFactory(c.accountId, this.config.dataDir);
      this._wireDriver(c.accountId, driver, null);
      try {
        await driver.start();
        console.log(
          `[bridge] restored ${c.accountId.slice(0, 8)} (${c.phone})`
        );
      } catch (e) {
        console.error(`[bridge] restore failed for ${c.accountId}:`, e);
      }
    }
  }

  private _wireDriver(
    accountId: string,
    driver: SocketDriver,
    session: PairSession | null
  ): void {
    driver.on("qr", async (p) => {
      if (!session) return; // restored accounts never need a QR
      session.qr_text = p.qr_text;
      const png = await QRCode.toDataURL(p.qr_text, { margin: 1, width: 320 });
      session.qr_image_b64 = png;
      session.updated_at = Date.now();
      if (session.state !== "paired") session.state = "qr";
    });
    driver.on("paired", (p) => {
      this.drivers.set(accountId, driver);
      this.accounts.set(accountId, { jid: p.jid, phone: p.phone_number });
      if (session) {
        session.jid = p.jid;
        session.phone_number = p.phone_number;
        session.state = "paired";
        session.updated_at = Date.now();
      }
      // Always tell core; for restores this lets the plugin re-populate
      // its in-memory account_for_jid maps without writing duplicate rows
      // (the link store's link() is idempotent on (channel, external_id)).
      void this.webhook.post(this.config.webhookUrl, this.config.webhookSecret, {
        type: "paired",
        account_id: accountId,
        jid: p.jid,
        phone_number: p.phone_number,
        restored: !session,
        ts: Date.now(),
      });
    });
    driver.on("message", (m: InboundMessage) => {
      // Driver already drops outbound echoes; anything reaching us here is
      // a legitimate inbound (including the user's own self-chat used for
      // testing).
      void this.webhook.post(this.config.webhookUrl, this.config.webhookSecret, {
        type: "message",
        account_id: accountId,
        jid: m.jid,
        phone_number: m.phone_number,
        chat_jid: m.chat_jid,
        is_group: m.is_group,
        message_id: m.message_id,
        text: m.text,
        timestamp: m.timestamp,
      });
    });
    driver.on("closed", () => {
      if (session && session.state !== "paired") {
        session.state = "failed";
        session.failure_reason = "connection closed before pairing";
        session.updated_at = Date.now();
      }
      this.drivers.delete(accountId);
    });
  }

  getPair(pair_id: string): PairSession | undefined {
    return this.pairs.get(pair_id);
  }

  // ---- send ------------------------------------------------------------

  async send(account_id: string, to_jid: string, text: string): Promise<void> {
    const driver = this.drivers.get(account_id);
    if (!driver) throw new Error(`account ${account_id} is not connected`);
    await driver.send(to_jid, text);
  }

  async listGroups(account_id: string) {
    const driver = this.drivers.get(account_id);
    if (!driver) throw new Error(`account ${account_id} is not connected`);
    return driver.listGroups();
  }

  async resolveInvite(account_id: string, code: string) {
    const driver = this.drivers.get(account_id);
    if (!driver) throw new Error(`account ${account_id} is not connected`);
    return driver.resolveInvite(code);
  }

  // ---- accounts --------------------------------------------------------

  listAccounts(): { account_id: string; jid: string; phone: string }[] {
    return [...this.accounts.entries()].map(([account_id, v]) => ({
      account_id,
      ...v,
    }));
  }

  async logout(account_id: string): Promise<boolean> {
    const driver = this.drivers.get(account_id);
    if (driver) {
      await driver.logout();
    }
    this.drivers.delete(account_id);
    this.accounts.delete(account_id);
    // Wipe persisted auth so subsequent pair won't auto-restore.
    try {
      await rm(resolve(this.config.dataDir, account_id), {
        recursive: true,
        force: true,
      });
    } catch {
      /* ignore */
    }
    return true;
  }
}
