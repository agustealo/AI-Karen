import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ChatMessage } from "@/lib/types";
import RichResultWorkspace from "@/components/chat/RichResultWorkspace";

const message = {
  id: "assistant-owned",
  role: "assistant",
  content: "Verified response",
  structuredContent: { result: { value: 1 } },
  artifacts: [{ id: "artifact-1", title: "Verified artifact", content: "Saved result" }],
  attachments: [{ id: "file-1", name: "report.txt", url: "/files/report.txt" }],
  citations: [{ id: "source-1", title: "Public source", url: "https://example.org/source" }],
} as unknown as ChatMessage;

describe("right-side result workspace preferences", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => cleanup());

  it("hides and restores an existing card while preserving other evidence", () => {
    render(<RichResultWorkspace message={message} />);
    fireEvent.click(screen.getByRole("button", { name: "Customize workspace cards" }));
    const toggle = screen.getByRole("checkbox", { name: "Artifacts" });
    fireEvent.click(toggle);
    expect(screen.queryByText("Verified artifact")).toBeNull();
    expect(screen.getByText("Public source")).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.getByText("Verified artifact")).toBeTruthy();
  });

  it("moves cards down and saves order for the next mount", () => {
    const view = render(<RichResultWorkspace message={message} />);
    fireEvent.click(screen.getByRole("button", { name: "Customize workspace cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Move Artifacts down" }));
    const saved = JSON.parse(window.localStorage.getItem("karen.workspace.cards.v1") || "{}");
    expect(saved.order).toEqual(["structured", "artifacts", "attachments", "evidence"]);
    view.unmount();
    render(<RichResultWorkspace message={message} />);
    expect(screen.getByRole("button", { name: "Customize workspace cards" })).toBeTruthy();
  });
});
