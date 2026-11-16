import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The optional browser-vendor adapter is disabled by default in production.
// Enable it only in this isolated component acceptance suite.
const previousFlag = vi.hoisted(() => {
  const previous = process.env.NEXT_PUBLIC_KAREN_BROWSER_DICTATION_ENABLED;
  process.env.NEXT_PUBLIC_KAREN_BROWSER_DICTATION_ENABLED = "true";
  return previous;
});

import { KarenBrowserDictationCapture } from "@/components/chat/KarenBrowserDictationCapture";

type Result = { results: ArrayLike<ArrayLike<{ transcript: string }>> };

class BrowserRecognition {
  static instances: BrowserRecognition[] = [];
  lang = "";
  interimResults = false;
  continuous = false;
  onresult: ((event: Result) => void) | null = null;
  onerror: (() => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();

  constructor() {
    BrowserRecognition.instances.push(this);
  }

  deliver(transcript: string) {
    this.onresult?.({ results: [[{ transcript }]] });
  }
}

function getPort(initial: string) {
  let text = initial;
  return {
    readText: () => text,
    writeText: vi.fn((updated: string) => { text = updated; }),
    updateDraft: (updated: string) => { text = updated; },
    current: () => text,
  };
}

function enableBrowserRecognition() {
  fireEvent.click(screen.getByRole("checkbox", {
    name: "Allow browser-vendor speech processing",
  }));
}

beforeEach(() => {
  BrowserRecognition.instances = [];
  Object.defineProperty(window, "webkitSpeechRecognition", {
    configurable: true, value: BrowserRecognition,
  });
});

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(window, "webkitSpeechRecognition");
  vi.restoreAllMocks();
});

afterAll(() => {
  if (previousFlag === undefined) {
    delete process.env.NEXT_PUBLIC_KAREN_BROWSER_DICTATION_ENABLED;
  } else {
    process.env.NEXT_PUBLIC_KAREN_BROWSER_DICTATION_ENABLED = previousFlag;
  }
});

describe("opt-in browser dictation and canonical live draft ownership", () => {
  it("does not start vendor recognition before the user grants consent", () => {
    const port = getPort("Private unsent draft");
    render(<KarenBrowserDictationCapture port={port} />);
    const start = screen.getByRole("button", { name: "Start browser dictation" });
    expect(start.hasAttribute("disabled")).toBe(true);
    expect(BrowserRecognition.instances).toHaveLength(0);
    expect(port.writeText).not.toHaveBeenCalled();
  });

  it("preserves typing that happened after microphone start, exactly once", () => {
    const port = getPort("Existing draft");
    render(<KarenBrowserDictationCapture port={port} />);
    enableBrowserRecognition();
    fireEvent.click(screen.getByRole("button", { name: "Start browser dictation" }));
    const active = BrowserRecognition.instances[0];
    expect(active.start).toHaveBeenCalledOnce();
    expect(port.writeText).not.toHaveBeenCalled();

    port.updateDraft("Existing draft plus later keyboard edits");
    act(() => active.deliver("spoken addition"));
    expect(port.current()).toBe("Existing draft plus later keyboard edits spoken addition");
    expect(port.writeText).toHaveBeenCalledTimes(1);
    act(() => active.deliver("spoken addition"));
    expect(port.writeText).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Stop dictation" })).toBeTruthy();
  });

  it("discards previous-session callbacks after the next recording begins", () => {
    const port = getPort("Original");
    render(<KarenBrowserDictationCapture port={port} />);
    enableBrowserRecognition();
    fireEvent.click(screen.getByRole("button", { name: "Start browser dictation" }));
    const retired = BrowserRecognition.instances[0];
    const staleResult = retired.onresult;
    const staleError = retired.onerror;
    const staleEnd = retired.onend;
    act(() => retired.onend?.());

    fireEvent.click(screen.getByRole("button", { name: "Start browser dictation" }));
    const active = BrowserRecognition.instances[1];
    expect(active).toBeDefined();
    act(() => {
      staleResult?.({ results: [[{ transcript: "wrong session" }]] });
      staleError?.();
      staleEnd?.();
    });
    expect(port.writeText).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Stop dictation" })).toBeTruthy();
    act(() => active.deliver("current session only"));
    expect(port.current()).toBe("Original current session only");
  });

  it("tears down recognition on unmount without modifying the draft", () => {
    const port = getPort("Unsent text");
    const view = render(<KarenBrowserDictationCapture port={port} />);
    enableBrowserRecognition();
    fireEvent.click(screen.getByRole("button", { name: "Start browser dictation" }));
    const active = BrowserRecognition.instances[0];
    const stale = active.onresult;
    view.unmount();
    expect(active.stop).toHaveBeenCalledOnce();
    act(() => stale?.({ results: [[{ transcript: "late vendor result" }]] }));
    expect(port.current()).toBe("Unsent text");
    expect(port.writeText).not.toHaveBeenCalled();
  });
});
