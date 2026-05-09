import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, LongTermMemoryOut } from "../../api/client";
import { MemorySection, ModeOption } from "./SettingsPage";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModeOption", () => {
  it("does not call onSelect when disabled", () => {
    const onSelect = vi.fn();
    render(
      <ModeOption
        current="allowlist"
        value="all"
        label="All conversations"
        description="Includes DMs"
        disabled
        disabledNote="DMs are not supported."
        onSelect={onSelect}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /all conversations/i }));

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
  });
});

describe("MemorySection", () => {
  it("pins a long-term memory row", async () => {
    const row: LongTermMemoryOut = {
      id: "mem-1",
      user_id: "user-1",
      project_id: null,
      kind: "fact",
      content: "Prefers storage internals examples.",
      weight: 0.8,
      pinned: false,
      meta: null,
      source_session_id: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    vi.spyOn(api, "listLongTermMemory").mockResolvedValue([row]);
    vi.spyOn(api, "updateLongTermMemory").mockResolvedValue({
      ...row,
      pinned: true,
    });

    render(<MemorySection />);

    expect(await screen.findByText(row.content)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^pin$/i }));

    await waitFor(() => {
      expect(api.updateLongTermMemory).toHaveBeenCalledWith("mem-1", {
        pinned: true,
      });
    });
    expect(screen.getAllByText(/^pinned$/i).length).toBeGreaterThan(0);
  });
});
