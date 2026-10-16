import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnswerCell } from "@/components/AnswerCell";
import { SafeMarkdown } from "@/components/Markdown";
import { ErrorState } from "@/components/States";
import { HashBadge, RunStateBadge } from "@/components/StatusBadge";
import { UsageTable } from "@/components/UsageTable";
import { ApiError } from "@/lib/api/client";

describe("status badges", () => {
  it("carry a text label, so state is never colour alone", () => {
    render(<RunStateBadge state="outcome_unknown" />);
    expect(screen.getByText("Outcome unknown")).toBeInTheDocument();
    render(<HashBadge status="line_ending_equivalent" />);
    expect(screen.getByText("Line-ending drift")).toBeInTheDocument();
  });

  it("never calls a request_started run failed or running", () => {
    render(<RunStateBadge state="outcome_unknown" />);
    const badge = screen.getByText("Outcome unknown").closest(".badge")!;
    expect(badge.getAttribute("title")).toMatch(/Not known to have failed, and not running/);
  });
});

describe("usage table", () => {
  it("renders null as unknown, estimated cost as estimated, and billed cost as not recorded", () => {
    render(<UsageTable caption="usage" rows={[
      { label: "Trial A", usage: { n_input_tokens: 0, n_output_tokens: 328, n_cache_tokens: null, cost_usd: 0.001037, cost_source: "estimated",
        provider: "gemini", model: "m", request_id: null, billed_cost_usd: null } },
      { label: "Missing", usage: null },
    ]} />);
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("0");
    expect(rows[1]).toHaveTextContent("unknown");
    expect(rows[1]).toHaveTextContent("(estimated)");
    expect(rows[1]).toHaveTextContent("Not recorded");
    expect(rows[2]).toHaveTextContent("unknown");
    expect(rows[2]).not.toHaveTextContent("$0");
  });
});

describe("answers", () => {
  it("falls back to the recorded code when the snapshot has no label", () => {
    render(<AnswerCell answer={{ question_id: "q", value: "mystery_code", label: null, label_source: "code_only", rationale: null, confidence: null }} />);
    expect(screen.getByText("mystery_code")).toBeInTheDocument();
    expect(screen.getByText(/No label in the recorded questionnaire/)).toBeInTheDocument();
    expect(screen.queryByText(/Rationale/)).not.toBeInTheDocument();
  });

  it("shows a recorded coercion", () => {
    render(<AnswerCell answer={{ question_id: "b", value: "true", label: "Yes", label_source: "questionnaire_snapshot", rationale: null, confidence: null }}
      coercion={{ question_id: "b", original: true, recorded: "true" }} />);
    expect(screen.getByText(/lossless JSON-boolean coercion/)).toBeInTheDocument();
  });
});

describe("markdown", () => {
  it("drops raw HTML and unsafe links from untrusted reports", () => {
    const { container } = render(<SafeMarkdown text={"# Report\n\n<script>alert(1)</script><img src=x onerror=alert(1)>\n\n[click](javascript:alert(1))"} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByText("click").closest("a");
    expect(link?.getAttribute("href") ?? "").not.toMatch(/javascript/i);
    expect(screen.getByRole("heading", { name: "Report" })).toBeInTheDocument();
  });
});

describe("error state", () => {
  it("explains network failures and retries on request", async () => {
    const retry = vi.fn();
    render(<ErrorState error={new ApiError(0, "network_error", "The SocietyTwin API could not be reached.", undefined, undefined, "network")} onRetry={retry} />);
    expect(screen.getByText(/Cannot reach the API/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("lists validation details and unavailable reasons without echoing input", () => {
    render(<ErrorState error={new ApiError(422, "invalid_request", "The request did not validate.", [{ loc: ["body", "size"], msg: "too large", type: "x" }], "r1")} />);
    expect(screen.getByText("size: too large")).toBeInTheDocument();
    render(<ErrorState error={new ApiError(503, "runtime_unavailable", "Unavailable.", { reasons: ["No MatrAIx checkout found."] })} />);
    expect(screen.getByText("No MatrAIx checkout found.")).toBeInTheDocument();
  });
});
