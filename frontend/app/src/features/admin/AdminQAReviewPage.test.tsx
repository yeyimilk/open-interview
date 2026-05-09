import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QASetOut, api } from "../../api/client";
import { AdminQAReviewPage } from "./AdminQAReviewPage";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdminQAReviewPage", () => {
  it("reviews and regenerates a QA set", async () => {
    const set: QASetOut = {
      id: "qa-1",
      project_id: "project-1",
      resume_id: null,
      scope: "project",
      position: "swe_generic",
      level: "mid",
      status: "ready",
      total: 4,
      error: null,
      review_status: "unreviewed",
      review_notes: null,
      reviewed_at: null,
      generation_run: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    vi.spyOn(api, "adminListQASets").mockResolvedValue([set]);
    vi.spyOn(api, "adminReviewQASet").mockResolvedValue({
      ...set,
      review_status: "approved",
    });
    vi.spyOn(api, "adminRegenerateQASet").mockResolvedValue({
      ...set,
      status: "pending",
    });

    render(
      <MemoryRouter>
        <AdminQAReviewPage />
      </MemoryRouter>
    );

    expect(await screen.findByText(/swe generic/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => {
      expect(api.adminReviewQASet).toHaveBeenCalledWith("qa-1", {
        review_status: "approved",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /regenerate/i }));

    await waitFor(() => {
      expect(api.adminRegenerateQASet).toHaveBeenCalledWith("qa-1");
    });
  });
});
