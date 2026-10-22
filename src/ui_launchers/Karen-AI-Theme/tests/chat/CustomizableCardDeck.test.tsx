import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import CustomizableCardDeck from "@/components/chat/CustomizableCardDeck";

const cards = [
  <Card key="execution"><CardHeader><CardTitle>Execution trace</CardTitle></CardHeader></Card>,
  <Card key="guardrails"><CardHeader><CardTitle>Guardrails & capabilities</CardTitle></CardHeader></Card>,
];

describe("conversation intelligence card preferences", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => cleanup());

  it("hides and restores a card without altering runtime-owned data", () => {
    render(<CustomizableCardDeck>{cards}</CustomizableCardDeck>);
    fireEvent.click(screen.getByRole("button", { name: "Customize intelligence cards" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Execution trace" }));
    expect(screen.getAllByText("Execution trace")).toHaveLength(1);
    fireEvent.click(screen.getByRole("checkbox", { name: "Execution trace" }));
    expect(screen.getAllByText("Execution trace")).toHaveLength(2);
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
  it("never allows local preferences to hide a human approval notice", () => {
    window.localStorage.setItem("karen.intelligence.cards.v1",
      JSON.stringify({ hidden: ["human-attention"], order: ["human-attention"] }));
    render(<CustomizableCardDeck>{[
      <Card key="approval"><CardHeader><CardTitle>Human attention</CardTitle></CardHeader></Card>,
    ]}</CustomizableCardDeck>);
    fireEvent.click(screen.getByRole("button", { name: "Customize intelligence cards" }));
    const toggle = screen.getByRole("checkbox", { name: /Human attention/ }) as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(toggle.checked).toBe(true);
    expect(screen.getAllByText("Human attention")).toHaveLength(1);
  });

});
