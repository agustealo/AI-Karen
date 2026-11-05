import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  KarenPresentationRegistry,
  parseKarenPresentation,
  presentationFromStructuredContent,
} from "@/components/chat/KarenPresentationRegistry";

const envelope = {
  schema_version: 1,
  presentation_id: "search-req-1",
  component_type: "search.results",
  evidence_ref: "req-1:web_search",
  correlation_id: "corr-1",
  data: {
    results: [
      {
        title: "Reported source headline",
        snippet: "Sourced description rather than a generated fact.",
        url: "https://example.org/news",
        published_at: "2026-11-05T09:00:00Z",
      },
      {
        snippet: "Another sourced description.",
        url: "https://example.org/second",
      },
    ],
  },
} as const;

describe("governed first-prompt search results", () => {
  it("renders plain-text source cards with provider-reported timestamps", () => {
    expect(parseKarenPresentation(envelope)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={envelope} />);
    expect(html).toContain("karen-search-results");
    expect(html).toContain("Reported source headline");
    expect(html).toContain("Sourced description");
    expect(html).toContain("Published (source-reported)");
    expect(html).toContain("https://example.org/news");
    expect(html).toContain("noopener noreferrer");
    expect(html).not.toContain("<script>");
  });

  it("replays the identical envelope from persisted structured content", () => {
    const saved = JSON.parse(JSON.stringify({ presentation: envelope }));
    const parsed = presentationFromStructuredContent(saved);
    expect(parsed).toEqual(envelope);
    expect(renderToStaticMarkup(<KarenPresentationRegistry data={parsed} />))
      .toContain("Reported source headline");
  });

  it("escapes source text, disallowing HTML and links in descriptions", () => {
    const payload = {
      ...envelope,
      data: {
        results: [{
          url: "https://example.org/article",
          title: "<img src=x onerror=alert(1)>",
          snippet: "<script>alert('x')</script>",
        }],
      },
    };
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={payload} />);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
  });

  it.each([
    "javascript:alert(1)",
    "file:///etc/passwd",
    "http://localhost:8010",
    "http://127.0.0.1/private",
    "http://192.168.0.1",
    "http://0x7f000001/",
    "https://example.org\\\\@127.0.0.1/",
    "https://person:password@example.org/data",
    "https://example.org/bad path",
  ])("rejects untrusted source URL %s", (url) => {
    expect(parseKarenPresentation({
      ...envelope, data: { results: [{ url, snippet: "Unsafe source" }] },
    })).toBeNull();
  });

  it("rejects duplicate source URLs, forged metadata and oversized text", () => {
    const one = envelope.data.results[0];
    expect(parseKarenPresentation({
      ...envelope, data: { results: [one, one] },
    })).toBeNull();
    expect(parseKarenPresentation({
      ...envelope, data: { results: [{ ...one, secret: "credential" }] },
    })).toBeNull();
    expect(parseKarenPresentation({
      ...envelope, data: { results: [{ ...one, snippet: "🌎".repeat(9_000) }] },
    })).toBeNull();
    expect(parseKarenPresentation({
      ...envelope,
      data: { results: Array.from({ length: 6 }, (_, index) => ({
        url: `https://example.org/${index}`, snippet: "Limited source",
      })) },
    })).toBeNull();
  });

  it("fails closed instead of mounting an unsupported renderer", () => {
    const html = renderToStaticMarkup(<KarenPresentationRegistry
      data={{ ...envelope, data: { results: [{ snippet: "No URL" }] } }}
    />);
    expect(html).toContain("Structured presentation unavailable");
    expect(html).not.toContain("karen-search-results");
  });
});
