export type ServerFrame =
  | { type: "ready"; session_id: string }
  | { type: "final_transcript"; text: string; voice?: any }
  | { type: "assistant_token"; text: string }
  | { type: "assistant_done" }
  | { type: "error"; message: string };

export type ClientFrame =
  | { type: "hello"; ticket: string }
  | { type: "config"; mime?: string; language?: string }
  | { type: "voice_start" }
  | { type: "end_user_turn" }
  | { type: "barge_in" }
  | { type: "mic_pause" }
  | { type: "mic_resume" }
  | { type: "bye" };
