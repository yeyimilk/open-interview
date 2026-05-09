import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api, ChatHistorySearchResult } from "../../api/client";
import { ChatHistoryPage } from "./ChatHistoryPage";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatHistoryPage", () => {
  it("uses the server search endpoint for message text", async () => {
    const row: ChatHistorySearchResult = {
      history_mode: "general",
      snippet: "user: Compare LSM storage compaction tradeoffs.",
      matched_message_count: 1,
      session: {
        id: "session-1",
        mode: "general",
        title: "Storage chat",
        project_id: null,
        target: null,
        status: "active",
        turn_count: 2,
        created_at: "2026-01-01T00:00:00Z",
      },
    };
    vi.spyOn(api, "listGeneralSessions").mockResolvedValue([]);
    vi.spyOn(api, "listMentorSessions").mockResolvedValue([]);
    vi.spyOn(api, "listInterviewerSessions").mockResolvedValue([]);
    vi.spyOn(api, "listProjects").mockResolvedValue([]);
    vi.spyOn(api, "searchChatHistory").mockResolvedValue([row]);

    render(
      <MemoryRouter>
        <ChatHistoryPage />
      </MemoryRouter>
    );

    await userEvent.type(
      screen.getByPlaceholderText(/search titles/i),
      "compaction"
    );

    await waitFor(() => {
      expect(api.searchChatHistory).toHaveBeenLastCalledWith({
        q: "compaction",
        mode: "all",
        project_id: "all",
        limit: 200,
      });
    });
    expect(await screen.findByText("Storage chat")).toBeInTheDocument();
    expect(screen.getByText(/LSM storage compaction/i)).toBeInTheDocument();
  });
});
