import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("canonical CopilotKit rail menu placement", () => {
  it("places the existing customization portal before the Conversations trigger", () => {
    const chat = source("src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx");
    expect(chat.indexOf('id="karen-rail-customize-menu"')).toBeLessThan(
      chat.indexOf('aria-label="Find conversations"'),
    );
    expect(chat).toContain('aria-hidden="true" className="hidden h-6 w-px bg-border xl:block"');
  });
  it("retains the card deck as the only visibility and order owner", () => {
    const deck = source("src/components/chat/CustomizableCardDeck.tsx");
    expect(deck).toContain("createPortal(trigger, headerTarget)");
    expect(deck).toContain("karen.intelligence.cards.v1");
    expect(deck).toContain('draggable={editing}');
    expect(deck).toContain('aria-label="Customize intelligence cards"');
  });
});
