import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import CustomizableCardDeck from "./CustomizableCardDeck";

const cards = (
  <>
    <Card><CardHeader><CardTitle>Execution trace</CardTitle></CardHeader></Card>
    <Card><CardHeader><CardTitle>Guardrails & capabilities</CardTitle></CardHeader></Card>
  </>
);

describe("conversation intelligence card preferences", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => cleanup());

  it("hides and restores a card without altering runtime-owned data", () => {
    render(<CustomizableCardDeck>{cards}</CustomizableCardDeck>);
    fireEvent.click(screen.getByRole("button", { name: "Customize intelligence cards" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Execution trace" }));
    expect(screen.queryByText("Execution trace", { selector: "[data-slot=card-title]" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Execution trace" }));
    expect(screen.getByText("Execution trace", { selector: "[data-slot=card-title]" })).toBeTruthy();
  });

  it("persists keyboard-driven reordering", () => {
    const view = render(<CustomizableCardDeck>{cards}</CustomizableCardDeck>);
    fireEvent.click(screen.getByRole("button", { name: "Customize intelligence cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Move Execution trace down" }));
    expect(JSON.parse(window.localStorage.getItem("karen.intelligence.cards.v1") || "{}").order)
      .toEqual(["guardrails-capabilities", "execution-trace"]);
    view.unmount();
    render(<CustomizableCardDeck>{cards}</CustomizableCardDeck>);
    expect(screen.getByText("Execution trace")).toBeTruthy();
  });
});
