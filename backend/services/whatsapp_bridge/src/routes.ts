// Fastify routes — thin wrappers over AccountManager. Auth is a single
// shared bearer token (the bridge is private to the local network).
import type { FastifyInstance } from "fastify";

import type { Config } from "./config.js";
import type { AccountManager } from "./manager.js";

export interface Deps {
  config: Config;
  manager: AccountManager;
}

export function registerRoutes(app: FastifyInstance, deps: Deps): void {
  app.addHook("onRequest", async (req, reply) => {
    if (req.url === "/health") return;
    const auth = req.headers.authorization ?? "";
    const expected = `Bearer ${deps.config.serviceToken}`;
    if (auth !== expected) {
      reply.code(401).send({ error: "unauthorized" });
    }
  });

  app.get("/health", async () => ({
    ok: true,
    ...deps.manager.stats(),
  }));

  app.post("/pair", async () => {
    const session = await deps.manager.startPair();
    return _publicSession(session);
  });

  app.get<{ Params: { pair_id: string } }>(
    "/pair/:pair_id/status",
    async (req, reply) => {
      const s = deps.manager.getPair(req.params.pair_id);
      if (!s) return reply.code(404).send({ error: "not_found" });
      return _publicSession(s);
    }
  );

  app.post<{
    Body: { account_id: string; to_jid: string; text: string };
  }>("/send", async (req, reply) => {
    const { account_id, to_jid, text } = req.body ?? ({} as any);
    if (!account_id || !to_jid || !text)
      return reply.code(400).send({ error: "missing_fields" });
    try {
      await deps.manager.send(account_id, to_jid, text);
      return { ok: true };
    } catch (e) {
      return reply.code(503).send({ error: (e as Error).message });
    }
  });

  app.get("/accounts", async () => ({
    accounts: deps.manager.listAccounts(),
  }));

  app.delete<{ Params: { account_id: string } }>(
    "/accounts/:account_id",
    async (req) => {
      const ok = await deps.manager.logout(req.params.account_id);
      return { ok };
    }
  );

  app.get<{ Params: { account_id: string } }>(
    "/accounts/:account_id/groups",
    async (req, reply) => {
      try {
        const groups = await deps.manager.listGroups(req.params.account_id);
        return { groups };
      } catch (e) {
        return reply.code(503).send({ error: (e as Error).message });
      }
    }
  );

  app.post<{
    Params: { account_id: string };
    Body: { code: string };
  }>("/accounts/:account_id/group-by-invite", async (req, reply) => {
    const code = (req.body?.code ?? "").trim();
    if (!code) return reply.code(400).send({ error: "missing_code" });
    try {
      const group = await deps.manager.resolveInvite(
        req.params.account_id,
        normalizeInviteCode(code)
      );
      return { group };
    } catch (e) {
      return reply.code(503).send({ error: (e as Error).message });
    }
  });
}

function normalizeInviteCode(input: string): string {
  // Accept full URLs ("https://chat.whatsapp.com/<code>") or bare codes.
  const m = input.match(/chat\.whatsapp\.com\/([A-Za-z0-9]+)/);
  return m ? m[1]! : input;
}

// Strip internal fields before responding.
function _publicSession(s: any) {
  return {
    pair_id: s.pair_id,
    account_id: s.account_id,
    state: s.state,
    qr_image_b64: s.qr_image_b64,
    qr_text: s.qr_text,
    phone_number: s.phone_number,
    jid: s.jid,
    failure_reason: s.failure_reason,
  };
}
