import { describe, expect, it } from "vitest";

import { BaileysDriver } from "../src/baileys-driver.js";

// We're testing pure helpers on BaileysDriver that don't depend on the
// network or the real Baileys library. Reach into private fields with a
// `as any` cast — this keeps the production API surface clean while
// still letting tests exercise the echo-suppression logic that protects
// us from group-chat infinite loops.
describe("BaileysDriver echo suppression", () => {
  it("flags a re-delivered message id as our own echo", () => {
    const drv = new BaileysDriver("acct-x", "/tmp/echo-test");
    const id = "ABC123";
    (drv as any).sentMessageIds.add(id);

    const echo = (drv as any)._isOwnEcho({
      messageId: id,
      chatJid: "g1@g.us",
      text: "hello",
      fromMe: true,
    });
    const notEcho = (drv as any)._isOwnEcho({
      messageId: id,
      chatJid: "g1@g.us",
      text: "hello",
      fromMe: true,
    });

    expect(echo).toBe(true);
    expect(notEcho).toBe(false);
  });

  it("flags a re-delivered text as echo when id is missing or unknown", () => {
    const drv = new BaileysDriver("acct-x", "/tmp/echo-test");
    (drv as any)._rememberSentText("g1@g.us", "  Hello  world  ");

    // Same chat + normalized-equivalent text → echo.
    expect(
      (drv as any)._isOwnEcho({
        messageId: "X",
        chatJid: "g1@g.us",
        text: "Hello world",
        fromMe: true,
      })
    ).toBe(true);

    // After consuming, a *different* message with same text isn't suppressed
    // (would be too aggressive).
    expect(
      (drv as any)._isOwnEcho({
        messageId: "Y",
        chatJid: "g1@g.us",
        text: "Hello world",
        fromMe: true,
      })
    ).toBe(false);
  });

  it("never suppresses fromMe=false messages", () => {
    const drv = new BaileysDriver("acct-x", "/tmp/echo-test");
    (drv as any)._rememberSentText("g1@g.us", "ping");
    expect(
      (drv as any)._isOwnEcho({
        messageId: "Z",
        chatJid: "g1@g.us",
        text: "ping",
        fromMe: false,
      })
    ).toBe(false);
  });

  it("scopes echo cache by chat jid", () => {
    const drv = new BaileysDriver("acct-x", "/tmp/echo-test");
    (drv as any)._rememberSentText("g1@g.us", "hi");
    expect(
      (drv as any)._isOwnEcho({
        messageId: "",
        chatJid: "g2@g.us", // different group
        text: "hi",
        fromMe: true,
      })
    ).toBe(false);
  });
});
