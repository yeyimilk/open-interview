export type ServerFrame =
  | { type: "ready"; session_id: string }
  | { type: "calibration_required"; duration_ms: number; sample_rate: number }
  | { type: "calibration_ready" }
  | { type: "calibration_error"; message: string; retryable?: boolean }
  | { type: "user_speech_started" }
  | { type: "user_speech_stopped" }
  | { type: "turn_ignored"; reason?: string }
  | { type: "final_transcript"; text: string; voice?: any }
  | { type: "assistant_token"; text: string }
  | { type: "assistant_done" }
  | { type: "error"; message: string };

export type ClientFrame =
  | { type: "hello"; ticket: string }
  | {
      type: "config";
      mime?: string;
      language?: string;
      audio_format?: "pcm16";
      sample_rate?: number;
      channels?: number;
    }
  | { type: "calibration_start" }
  | { type: "calibration_commit" }
  | { type: "barge_in" }
  | { type: "mic_pause" }
  | { type: "mic_resume" }
  | { type: "bye" };
