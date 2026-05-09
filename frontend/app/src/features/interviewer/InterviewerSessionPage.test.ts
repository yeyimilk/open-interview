import { describe, expect, it } from "vitest";
import { ChatMessageOut } from "../../api/client";
import { latestAssistantAction } from "./InterviewerSessionPage";

describe("latestAssistantAction", () => {
  it("reads the newest assistant action metadata", () => {
    const messages: ChatMessageOut[] = [
      {
        id: "m1",
        session_id: "s1",
        role: "assistant",
        content: "First",
        meta: { next_action: "ask_follow_up" },
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "m2",
        session_id: "s1",
        role: "user",
        content: "Answer",
        meta: null,
        created_at: "2026-01-01T00:00:01Z",
      },
      {
        id: "m3",
        session_id: "s1",
        role: "assistant",
        content: "Next topic",
        meta: { thread_state: { last_action: "switch_topic" } },
        created_at: "2026-01-01T00:00:02Z",
      },
    ];

    expect(latestAssistantAction(messages)).toBe("switch_topic");
  });
});
