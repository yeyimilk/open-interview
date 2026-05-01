// Real Baileys driver. Constructed once per account so multiple users
// can pair their personal numbers concurrently.
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { EventEmitter } from "node:events";

import pino from "pino";

import type { SocketDriver } from "./types.js";

// Baileys expects a full pino-compatible logger (with .error, .info, .child,
// .trace, .debug, .warn, .fatal). Use a real pino instance pinned to "warn"
// to keep its noise out of the bridge logs.
const baileysLogger: any = pino({ level: "warn" });

// Baileys 7.x exports named members at the top level (no default export).
// Older builds wrapped them under `default`, so we accept either shape.
async function importBaileys() {
  const m: any = await import("@whiskeysockets/baileys");
  if (typeof m.useMultiFileAuthState === "function") return m;
  if (m.default && typeof m.default.useMultiFileAuthState === "function") {
    return m.default;
  }
  throw new Error(
    "Could not find useMultiFileAuthState on @whiskeysockets/baileys export"
  );
}

// WhatsApp closes the socket with statusCode 515 immediately after a QR
// scan ("restart required") — this is normal; we have to reconnect with
// the freshly-saved creds and the next "open" is the real pairing event.
// 428 (connectionClosed) and 408 (timedOut) are also transient.
const RECONNECT_STATUS_CODES = new Set([408, 428, 515]);
const MAX_RECONNECTS = 5;

export class BaileysDriver implements SocketDriver {
  private emitter = new EventEmitter();
  private sock: any = null;
  private accountDir: string;
  private baileys: any = null;
  private authState: any = null;
  private saveCreds: (() => Promise<void>) | null = null;
  private version: [number, number, number] | undefined;
  private reconnects = 0;
  private stopped = false;
  // Echo-suppression: WhatsApp re-broadcasts every message we send back
  // through `messages.upsert` with `fromMe: true`. Without filtering,
  // groups become an infinite loop (bot reads its own reply, treats it
  // as a new owner turn, replies again, ...). We track:
  //   sentMessageIds:  message-key ids returned by sendMessage()
  //   sentTexts:       (chatJid, normalized-text) recently sent — Baileys
  //                    sometimes echoes the message *before* sendMessage()
  //                    resolves, so id-based dedup races. The text-based
  //                    fallback closes the gap.
  // Both sets are bounded so they can't grow without limit.
  private sentMessageIds: Set<string> = new Set();
  private sentTextEchoes: Map<string, number> = new Map(); // key=jid::normText, val=expiresAtMs
  private static readonly ECHO_TTL_MS = 60_000;
  private static readonly MAX_ECHO_CACHE = 256;

  constructor(
    private readonly accountId: string,
    dataDir: string
  ) {
    this.accountDir = resolve(dataDir, this.accountId);
  }

  on(event: "qr" | "paired" | "message" | "closed", cb: (p: any) => void) {
    this.emitter.on(event, cb);
  }

  async start(): Promise<void> {
    await mkdir(this.accountDir, { recursive: true });
    this.baileys = await importBaileys();
    const { state, saveCreds } = await this.baileys.useMultiFileAuthState(
      this.accountDir
    );
    this.authState = state;
    this.saveCreds = saveCreds;

    // Latest WA Web protocol version — outdated builds hit 405/515 loops.
    try {
      const fetched = await this.baileys.fetchLatestBaileysVersion();
      this.version = fetched?.version;
    } catch {
      /* offline / DNS issues — fall back to bundled version */
    }

    await this._connectOnce();
  }

  private async _connectOnce(): Promise<void> {
    const baileys = this.baileys;
    this.sock = baileys.makeWASocket({
      auth: this.authState,
      logger: baileysLogger,
      browser: baileys.Browsers?.macOS?.("Desktop") ?? [
        "Open Interview",
        "Desktop",
        "1.0.0",
      ],
      // Skip the (slow, sometimes-stalls) full history sync. Old messages
      // aren't useful to the bot anyway; we only care about new ones.
      syncFullHistory: false,
      // Mark the device as online so push messages start flowing
      // immediately rather than waiting for a manual presence update.
      markOnlineOnConnect: true,
      ...(this.version ? { version: this.version } : {}),
    });

    this.sock.ev.on("creds.update", this.saveCreds!);
    this.sock.ev.on("connection.update", (u: any) => {
      const code = u.lastDisconnect?.error?.output?.statusCode;
      console.log(
        `[baileys ${this.accountId.slice(0, 8)}] connection.update`,
        JSON.stringify({
          connection: u.connection,
          hasQr: !!u.qr,
          isNewLogin: u.isNewLogin,
          err: code,
          msg: u.lastDisconnect?.error?.message,
        })
      );

      if (u.qr) this.emitter.emit("qr", { qr_text: u.qr });

      if (u.connection === "open") {
        this.reconnects = 0;
        const me = this.sock.user;
        const jid = me?.id ?? "";
        const phone = jidToPhone(jid);
        this.emitter.emit("paired", { jid, phone_number: phone });
      }

      if (u.connection === "close") {
        const retryable =
          !this.stopped &&
          (RECONNECT_STATUS_CODES.has(code) || code === undefined) &&
          this.reconnects < MAX_RECONNECTS;
        if (retryable) {
          this.reconnects += 1;
          console.log(
            `[baileys ${this.accountId.slice(0, 8)}] reconnecting (${
              this.reconnects
            }/${MAX_RECONNECTS}) after code=${code}`
          );
          // Brief backoff to avoid hammering on transient errors.
          setTimeout(() => {
            this._connectOnce().catch((e) => {
              console.error(
                `[baileys ${this.accountId.slice(0, 8)}] reconnect failed`,
                e
              );
              this.emitter.emit("closed", { reason: "reconnect_failed" });
            });
          }, 750);
          return;
        }
        this.emitter.emit("closed", { reason: code ?? "unknown" });
      }
    });

    // While debugging the round trip, dump every event Baileys fires
    // so we can tell the difference between "no message arrived" and
    // "message arrived but was filtered". Set BAILEYS_DEBUG=0 to disable.
    if (process.env.BAILEYS_DEBUG !== "0") {
      this.sock.ev.process((events: any) => {
        const keys = Object.keys(events);
        if (keys.length > 0) {
          console.log(
            `[baileys ${this.accountId.slice(0, 8)}] ev`,
            JSON.stringify(keys)
          );
        }
      });
    }

    this.sock.ev.on("messages.upsert", (m: any) => {
      const ownJid = phoneFromMe(this.sock.user?.id);
      console.log(
        `[baileys ${this.accountId.slice(0, 8)}] upsert`,
        JSON.stringify({
          type: m.type,
          count: (m.messages ?? []).length,
        })
      );
      for (const msg of m.messages ?? []) {
        // Whatever shape we got, log a one-line summary so we can see why
        // a message might be skipped.
        console.log(
          `[baileys ${this.accountId.slice(0, 8)}] raw`,
          JSON.stringify({
            hasMessage: !!msg.message,
            messageKeys: msg.message ? Object.keys(msg.message) : [],
            messageStubType: msg.messageStubType,
            fromMe: !!msg.key?.fromMe,
            remoteJid: msg.key?.remoteJid,
            participant: msg.key?.participant,
          })
        );
        if (!msg.message) continue;
        const fromMe = !!msg.key.fromMe;
        const remoteJid: string = msg.key.remoteJid ?? "";
        const isGroup = remoteJid.endsWith("@g.us");
        const isDm = remoteJid.endsWith("@s.whatsapp.net");
        if (!isGroup && !isDm) continue;
        const text = extractText(msg.message);
        if (!text) {
          console.log(
            `[baileys ${this.accountId.slice(0, 8)}] no-text`,
            JSON.stringify({
              keys: Object.keys(msg.message ?? {}),
              fromMe: !!msg.key.fromMe,
              chat: remoteJid,
              // Help debug self-chat envelopes — WhatsApp wraps real text
              // in protocolMessage of various subtypes.
              protocolType: msg.message?.protocolMessage?.type,
              protocolKeys: msg.message?.protocolMessage
                ? Object.keys(msg.message.protocolMessage)
                : [],
            })
          );
          continue;
        }
        // For group messages the actual sender lives in key.participant.
        // Newer WhatsApp uses opaque "@lid" identifiers there which our
        // downstream code doesn't recognise; if it's the linked owner
        // (fromMe), substitute their real phone JID so filters/link
        // resolution behave like a normal DM-from-owner.
        const ownerJid: string = this.sock.user?.id ?? "";
        let senderJid: string;
        if (isGroup) {
          if (fromMe && ownerJid) {
            senderJid = ownerJid;
          } else {
            senderJid = msg.key.participant ?? remoteJid;
          }
        } else {
          senderJid = remoteJid;
        }
        // Echo suppression: WhatsApp re-delivers every message we send
        // back through this same channel with fromMe=true. Without this
        // check, the bot reads its own reply, treats it as a new owner
        // turn, replies to it, and so on — infinite loop. We compare
        // against ids returned by sendMessage() and against recently-
        // sent (chat, text) pairs as a fallback.
        if (
          this._isOwnEcho({
            messageId: msg.key.id ?? "",
            chatJid: remoteJid,
            text,
            fromMe,
          })
        ) {
          console.log(
            `[baileys ${this.accountId.slice(0, 8)}] echo-skip`,
            JSON.stringify({
              chat: remoteJid,
              id: msg.key.id ?? "",
              text: text.slice(0, 60),
            })
          );
          continue;
        }
        // Decide whether to keep "fromMe" messages.
        //   - In a 1:1 self-chat (sender = recipient = the linked owner)
        //     we keep them so users can test the bot solo.
        //   - In a group, fromMe still means a human typed something on
        //     their phone — we keep those too so the bot can answer
        //     prompts the owner sends in their own group.
        //   - In any OTHER 1:1 (you DMing some other contact from your
        //     phone), we skip — that's a private chat with someone else
        //     and the bot has no business chiming in.
        if (fromMe && !isGroup) {
          const isSelfChat = jidToPhone(remoteJid) === ownJid;
          if (!isSelfChat) continue;
        }
        // Useful debugging while wiring up the message round trip.
        console.log(
          `[baileys ${this.accountId.slice(0, 8)}] msg`,
          JSON.stringify({
            from: senderJid,
            chat: remoteJid,
            isGroup,
            fromMe,
            text: text.slice(0, 80),
          })
        );
        this.emitter.emit("message", {
          jid: senderJid,
          phone_number: jidToPhone(senderJid),
          chat_jid: remoteJid,
          is_group: isGroup,
          message_id: msg.key.id ?? "",
          text,
          timestamp: (msg.messageTimestamp ?? Date.now() / 1000) * 1000,
          is_from_me: fromMe,
        });
      }
    });
  }

  async send(jid: string, text: string): Promise<void> {
    if (!this.sock) throw new Error("socket not connected");
    // Pre-stamp the echo cache BEFORE sending — otherwise the inbound
    // upsert can race with the sendMessage promise.
    this._rememberSentText(jid, text);
    const result: any = await this.sock.sendMessage(jid, { text });
    const id: string | undefined = result?.key?.id;
    if (id) {
      this.sentMessageIds.add(id);
      // Bound the set — old ids are unlikely to come back.
      if (this.sentMessageIds.size > BaileysDriver.MAX_ECHO_CACHE) {
        const first = this.sentMessageIds.values().next().value;
        if (first) this.sentMessageIds.delete(first);
      }
    }
  }

  private _normText(text: string): string {
    return text.trim().replace(/\s+/g, " ");
  }

  private _rememberSentText(jid: string, text: string): void {
    const key = `${jid}::${this._normText(text)}`;
    const expires = Date.now() + BaileysDriver.ECHO_TTL_MS;
    this.sentTextEchoes.set(key, expires);
    // Best-effort GC.
    if (this.sentTextEchoes.size > BaileysDriver.MAX_ECHO_CACHE) {
      const now = Date.now();
      for (const [k, exp] of this.sentTextEchoes) {
        if (exp <= now) this.sentTextEchoes.delete(k);
      }
    }
  }

  private _isOwnEcho(args: {
    messageId: string;
    chatJid: string;
    text: string;
    fromMe: boolean;
  }): boolean {
    if (!args.fromMe) return false;
    if (args.messageId && this.sentMessageIds.has(args.messageId)) {
      this.sentMessageIds.delete(args.messageId);
      return true;
    }
    const key = `${args.chatJid}::${this._normText(args.text)}`;
    const exp = this.sentTextEchoes.get(key);
    if (exp && exp > Date.now()) {
      // Consume it so a *real* identical message later isn't suppressed.
      this.sentTextEchoes.delete(key);
      return true;
    }
    return false;
  }

  async listGroups() {
    if (!this.sock) throw new Error("socket not connected");
    const map = (await this.sock.groupFetchAllParticipating()) as Record<
      string,
      any
    >;
    const out: { jid: string; subject: string; participants_count: number }[] = [];
    for (const g of Object.values(map ?? {})) {
      out.push({
        jid: g.id,
        subject: g.subject ?? "(untitled)",
        participants_count: Array.isArray(g.participants)
          ? g.participants.length
          : 0,
      });
    }
    return out.sort((a, b) => a.subject.localeCompare(b.subject));
  }

  async resolveInvite(code: string) {
    if (!this.sock) throw new Error("socket not connected");
    // groupGetInviteInfo returns metadata WITHOUT joining the group.
    const meta = await this.sock.groupGetInviteInfo(code);
    return {
      jid: meta.id,
      subject: meta.subject ?? "(untitled)",
      participants_count: Array.isArray(meta.participants)
        ? meta.participants.length
        : meta.size ?? 0,
    };
  }

  async logout(): Promise<void> {
    this.stopped = true;
    try {
      await this.sock?.logout?.();
    } catch {
      /* ignore */
    }
    this.sock = null;
  }
}

function jidToPhone(jid: string): string {
  const at = jid.indexOf("@");
  const local = at === -1 ? jid : jid.slice(0, at);
  const colon = local.indexOf(":");
  return colon === -1 ? local : local.slice(0, colon);
}

function phoneFromMe(id: string | undefined): string {
  return id ? jidToPhone(id) : "";
}

function extractText(message: any): string {
  if (!message) return "";
  // WhatsApp wraps the real payload inside ephemeral / view-once / device
  // envelopes; unwrap until we hit a leaf.
  for (let i = 0; i < 5; i++) {
    if (message.ephemeralMessage?.message) {
      message = message.ephemeralMessage.message;
      continue;
    }
    if (message.viewOnceMessage?.message) {
      message = message.viewOnceMessage.message;
      continue;
    }
    if (message.viewOnceMessageV2?.message) {
      message = message.viewOnceMessageV2.message;
      continue;
    }
    if (message.deviceSentMessage?.message) {
      message = message.deviceSentMessage.message;
      continue;
    }
    if (message.documentWithCaptionMessage?.message) {
      message = message.documentWithCaptionMessage.message;
      continue;
    }
    break;
  }
  if (typeof message.conversation === "string") return message.conversation;
  if (message.extendedTextMessage?.text) return message.extendedTextMessage.text;
  if (message.imageMessage?.caption) return message.imageMessage.caption;
  if (message.videoMessage?.caption) return message.videoMessage.caption;
  if (message.buttonsResponseMessage?.selectedDisplayText)
    return message.buttonsResponseMessage.selectedDisplayText;
  if (message.listResponseMessage?.title) return message.listResponseMessage.title;
  if (message.templateButtonReplyMessage?.selectedDisplayText)
    return message.templateButtonReplyMessage.selectedDisplayText;
  return "";
}
