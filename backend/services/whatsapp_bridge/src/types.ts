// Bridge-internal types. All times are ms since epoch.

export type PairState =
  | "waiting" // socket up, no QR yet
  | "qr" // QR available, user has not scanned
  | "paired" // QR scanned, socket open and authenticated
  | "failed"; // gave up / explicitly cancelled

export interface PairSession {
  pair_id: string;
  account_id: string;
  state: PairState;
  qr_image_b64: string | null;
  qr_text: string | null;
  phone_number: string | null;
  jid: string | null;
  failure_reason: string | null;
  created_at: number;
  updated_at: number;
}

export interface InboundMessage {
  account_id: string;
  jid: string; // sender wa-jid (e.g. 15551234567@s.whatsapp.net)
  phone_number: string;
  chat_jid?: string; // the conversation: same as jid for DMs, group jid otherwise
  is_group?: boolean;
  message_id: string;
  text: string;
  timestamp: number;
  is_from_me: boolean;
}

export interface GroupSummary {
  jid: string; // "<creator-phone>-<timestamp>@g.us"
  subject: string;
  participants_count: number;
}

// Driver abstraction so we can plug a fake socket in tests.
export interface SocketDriver {
  /** Begin a new pairing session. The driver MUST emit a "qr" event with
   * the QR text on connect.update, and a "paired" event once authenticated. */
  start(): Promise<void>;
  send(jid: string, text: string): Promise<void>;
  logout(): Promise<void>;
  /** List groups this account participates in. Only valid post-pairing. */
  listGroups(): Promise<GroupSummary[]>;
  /** Resolve a https://chat.whatsapp.com/<code> invite to a GroupSummary
   * WITHOUT joining the group. */
  resolveInvite(code: string): Promise<GroupSummary>;
  on(
    event: "qr" | "paired" | "message" | "closed",
    cb: (payload: any) => void
  ): void;
}
