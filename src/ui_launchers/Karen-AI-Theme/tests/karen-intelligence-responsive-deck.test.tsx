import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import CustomizableCardDeck from "@/components/chat/CustomizableCardDeck";

afterEach(() => {
  cleanup();
  document.getElementById("karen-rail-customize-menu")?.remove();
  window.localStorage.removeItem("karen.intelligence.cards.v1");
});

describe("canonical intelligence deck responsive customization", () => {
  it("keeps embedded controls in their own disclosure instead of duplicating the desktop portal", () => {
    const portal = document.createElement("div");
    portal.id = "karen-rail-customize-menu";
    document.body.appendChild(portal);
    const view = render(
      <>
        <div data-testid="mobile-deck">
          <CustomizableCardDeck portalEnabled={false}>
            <div>Mobile intelligence</div>
          </CustomizableCardDeck>
        </div>
        <div data-testid="desktop-deck">
          <CustomizableCardDeck>
            <div>Desktop intelligence</div>
          </CustomizableCardDeck>
        </div>
      </>,
    );

    expect(portal.querySelectorAll('button[aria-label="Customize intelligence cards"]')).toHaveLength(1);
    expect(screen.getByTestId("mobile-deck").querySelectorAll('button[aria-label="Customize intelligence cards"]')).toHaveLength(1);
    expect(screen.getByTestId("desktop-deck").querySelectorAll('button[aria-label="Customize intelligence cards"]')).toHaveLength(0);
    view.unmount();
  });
});
