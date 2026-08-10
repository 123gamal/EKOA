import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalPanel } from "./ApprovalPanel";

describe("ApprovalPanel", () => {
  it("renders the workflow name and decision buttons", () => {
    render(
      <ApprovalPanel
        workflowName="HR Data Sweep"
        isSubmitting={false}
        onSubmit={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.getByText(/awaiting human approval/i)).toBeInTheDocument();
    expect(screen.getByText("HR Data Sweep")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/reason/i)).toBeInTheDocument();
  });

  it("submits the typed reason when approving", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ApprovalPanel
        workflowName="HR Data Sweep"
        isSubmitting={false}
        onSubmit={onSubmit}
        onReject={vi.fn()}
      />
    );

    await user.type(screen.getByLabelText(/reason/i), "Reviewed — no true leak");
    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(onSubmit).toHaveBeenCalledWith({ reason: "Reviewed — no true leak" });
  });

  it("calls onReject with the current reason when rejecting", async () => {
    const user = userEvent.setup();
    const onReject = vi.fn();
    render(
      <ApprovalPanel
        workflowName="HR Data Sweep"
        isSubmitting={false}
        onSubmit={vi.fn()}
        onReject={onReject}
      />
    );

    await user.type(screen.getByLabelText(/reason/i), "Escalate to compliance");
    await user.click(screen.getByRole("button", { name: /reject/i }));

    expect(onReject).toHaveBeenCalledWith({ reason: "Escalate to compliance" });
  });

  it("disables the decision buttons while submitting", () => {
    render(
      <ApprovalPanel
        workflowName="HR Data Sweep"
        isSubmitting={true}
        onSubmit={vi.fn()}
        onReject={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
  });
});
