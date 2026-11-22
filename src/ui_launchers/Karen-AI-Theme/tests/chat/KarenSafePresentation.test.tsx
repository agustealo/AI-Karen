import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/components/chat/KarenPresentationRegistry", () => ({
  KarenPresentationRegistry: ({ data }: { data: unknown }) => {
    if (data === "broken") throw new Error("Simulated card renderer failure");
    return <p>Verified neighboring card</p>;
  },
}));

import { KarenSafePresentation } from "@/components/chat/KarenSafePresentation";

describe("chat card failure containment", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps neighboring cards readable after one renderer throws", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <>
        <p>Saved assistant answer</p>
        <KarenSafePresentation data="broken" />
        <KarenSafePresentation data="valid" />
      </>,
    );
    expect(screen.getByText("Saved assistant answer")).toBeTruthy();
    expect(screen.getByTestId("karen-presentation-render-error")).toBeTruthy();
    expect(screen.getByText("Verified neighboring card")).toBeTruthy();
    expect(log).toHaveBeenCalled();
  });
});
