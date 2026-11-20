import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { KarenPresentationRegistry, parseKarenPresentation, presentationFromStructuredContent } from "@/components/chat/KarenPresentationRegistry";

const valid = {
  schema_version: 1,
  presentation_id: "weather-detroit-1",
  evidence_ref: "tool-weather-result-1",
  component_type: "weather.observation",
  data: { location: "Detroit, Michigan", temperature_f: 60.3, wind_speed_mph: 0.3 },
} as const;

describe("verified date observation", () => {
  const observation = {
    schema_version: 1,
    presentation_id: "date-20261029",
    evidence_ref: "request-1:time-query",
    component_type: "date.observation",
    data: { formatted: "2026-10-29", timezone: "America/Detroit" },
  };
  it("presents the backed date without converting timezones", () => {
    expect(parseKarenPresentation(observation)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={observation} />);
    expect(html).toContain("Thursday, October 29, 2026");
    expect(html).toContain("America/Detroit");
    expect(html).toContain("karen-date-presentation");
  });
  it("rejects invalid calendar days and unapproved fields", () => {
    expect(parseKarenPresentation({
      ...observation, data: { formatted: "2026-02-30" },
    })).toBeNull();
    expect(parseKarenPresentation({
      ...observation, data: { formatted: "2026-10-29", private: "secret" },
    })).toBeNull();
  });
});

describe("versioned presentation registry", () => {

  it("restores a bounded composed surface with independently referenced evidence", () => {
    const clock = {
      schema_version: 1, presentation_id: "clock-1",
      evidence_ref: "receipt-clock", component_type: "time.observation",
      data: { formatted: "10:15 AM", timezone: "America/Detroit" },
    };
    const weather = { ...valid, evidence_ref: "receipt-weather" };
    const composed = {
      schema_version: 1, presentation_id: "surface-1",
      evidence_ref: "conversation-surface",
      component_type: "surface.composition",
      data: {
        layout: "grid",
        evidence_refs: ["receipt-clock", "receipt-weather"],
        items: [clock, weather],
      },
    };
    const persisted = JSON.parse(JSON.stringify({ presentation: composed }));
    const restored = presentationFromStructuredContent(persisted);
    expect(restored?.presentation_id).toBe("surface-1");
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={restored} />);
    expect(html).toContain("10:15 AM");
    expect(html).toContain("Detroit");
    expect(html).toContain("karen-composed-surface");
    expect(parseKarenPresentation({
      ...composed,
      data: { ...composed.data, evidence_refs: ["receipt-clock", "forged"] },
    })).toBeNull();
  });

  it("renders only validated read-only planner tasks", () => {
    const envelope = {
      ...valid,
      component_type: "planner.task_list",
      data: { tasks: [
        { id: "task-1", title: "Review project", status: "todo" },
        { id: "task-2", title: "Approve draft", status: "cancelled" },
      ] },
    };
    expect(parseKarenPresentation(envelope)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={envelope} />);
    expect(html).toContain("Review project");
    expect(html).toContain("Approve draft");
    expect(html).not.toContain("<button");
    expect(parseKarenPresentation({ ...envelope, data: { tasks: [{ id: "x", title: "Unsafe", status: "executed" }] } })).toBeNull();
  });

  it("restores only allowlisted envelopes nested in canonical metadata", () => {
    expect(presentationFromStructuredContent({ presentation: valid })?.presentation_id).toBe(valid.presentation_id);
    expect(presentationFromStructuredContent(valid)).toBeNull();
    expect(presentationFromStructuredContent({ presentation: { ...valid, evidence_ref: "" } })).toBeNull();
    expect(presentationFromStructuredContent({ presentation: { ...valid, component_type: "unsafe.html" } })).toBeNull();
    expect(presentationFromStructuredContent(null)).toBeNull();
    expect(presentationFromStructuredContent([])).toBeNull();
  });

  it("renders validated weather evidence", () => {
    expect(parseKarenPresentation(valid)?.presentation_id).toBe("weather-detroit-1");
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={valid} />);
    expect(html).toContain("Detroit");
    expect(html).toContain("0.3");
    expect(html).toContain("mph");
  });

  it("renders short verified condition text without fabricating a weather code", () => {
    const reported = {
      ...valid,
      data: {
        location: "Detroit, Michigan", temperature: "61°F",
        conditions: "light rain", private_note: "do not display",
      },
    };
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={reported} />);
    expect(parseKarenPresentation(reported)).not.toBeNull();
    expect(html).toContain("light rain");
    expect(html).not.toContain("private_note");
    expect(html).not.toContain("do not display");
    expect(html).toContain("karen-weather-presentation");
    expect(parseKarenPresentation({
      ...reported, data: { ...reported.data, conditions: "s".repeat(121) },
    })).toBeNull();
    expect(parseKarenPresentation({
      ...reported, data: { ...reported.data, condition: "different reading" },
    })).toBeNull();
  });

  it("renders verified weather comparisons without synthesizing any measurements", () => {
    const comparison = { ...valid, component_type: "weather.comparison", data: [
      valid.data,
      { location: "New York, NY", temperature_f: 62, wind_speed_mph: 2 },
    ] };
    expect(parseKarenPresentation(comparison)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={comparison} />);
    expect(html).toContain("Detroit");
    expect(html).toContain("New York");
    expect(html).toContain("0.3 mph");
    expect(html).toContain("2 mph");
    expect(parseKarenPresentation({ ...comparison, data: [valid.data] })).toBeNull();
    expect(parseKarenPresentation({ ...comparison, data: [valid.data, { ...valid.data, location: " detroit, michigan " }] })).toBeNull();
    expect(parseKarenPresentation({ ...comparison, data: [valid.data, { location: "Bad", temperature_f: 500 }] })).toBeNull();
  });

  it("fails closed for unknown versions and components", () => {
    expect(parseKarenPresentation({ ...valid, schema_version: 2 })).toBeNull();
    expect(parseKarenPresentation({ ...valid, component_type: "unsafe.html" })).toBeNull();
    expect(parseKarenPresentation({ ...valid, inject: "<script/>" })).toBeNull();
  });

  it("requires provenance and bounds oversized payloads", () => {
    const { evidence_ref: _discard, ...withoutEvidence } = valid;
    expect(parseKarenPresentation(withoutEvidence)).toBeNull();
    expect(parseKarenPresentation({ ...valid, data: { ...valid.data, notes: "x".repeat(40_000) } })).toBeNull();
  });

  it("enforces the backend UTF-8 byte limit for multibyte weather location data", () => {
    const envelope = {
      ...valid,
      data: { ...valid.data, location: "🌤".repeat(9_000) },
    };
    expect(JSON.stringify(envelope).length).toBeLessThan(32_768);
    expect(new TextEncoder().encode(JSON.stringify(envelope)).byteLength).toBeGreaterThan(32_768);
    expect(parseKarenPresentation(envelope)).toBeNull();
  });

  it("rejects mismatched or malformed data", () => {
    expect(parseKarenPresentation({ ...valid, data: { temperature_f: 60 } })).toBeNull();
    expect(parseKarenPresentation({ ...valid, data: { location: "NYC", temperature_f: 999 } })).toBeNull();
  });

  it("offers a non-executing text fallback", () => {
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={{ version: "unknown" }} />);
    expect(html).toContain("Structured presentation unavailable");
    expect(html).not.toContain("<script");
  });
});


describe("search source link parity", () => {
  const base = {
    schema_version: 1, presentation_id: "search-parity",
    component_type: "search.results", evidence_ref: "source-receipt-1",
    data: { results: [{ url: "https://example.com/story", snippet: "Reported event" }] },
  };
  it("disallows fragment-bearing source links", () => {
    expect(parseKarenPresentation(base)).not.toBeNull();
    expect(parseKarenPresentation({ ...base, data: { results: [{ ...base.data.results[0], url: "https://example.com/story#section" }] } })).toBeNull();
  });
});

describe("bounded reusable data table", () => {
  const data = {
    schema_version: 1, presentation_id: "table-one",
    component_type: "data.table", evidence_ref: "authorized-research-1",
    data: {
      title: "Research comparison",
      columns: [{ key: "item", label: "Item" }, { key: "fact", label: "Reported fact" }],
      rows: [{ item: "A", fact: "Reported observation" }, { item: "B", fact: null }],
    },
  };
  it("renders accessible static table and preserves replay", () => {
    const persisted = JSON.parse(JSON.stringify({ presentation: data }));
    expect(presentationFromStructuredContent(persisted)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={data} />);
    expect(html).toContain("karen-data-table");
    expect(html).toContain("<table");
    expect(html).toContain("scope=\"col\"");
    expect(html).toContain("Reported observation");
    expect(html).toContain("Not provided");
    expect(html).not.toContain("<button");
  });
  it("renders authorized source URL cells as safe links after persisted replay", () => {
    const sourceData = {
      ...data,
      data: {
        title: "Verified search source excerpts",
        columns: [
          { key: "source_title", label: "Source title" },
          { key: "source_url", label: "Source URL" },
        ],
        rows: [{ source_title: "Publisher", source_url: "https://example.org/news" }],
      },
    };
    const persisted = JSON.parse(JSON.stringify({ presentation: sourceData }));
    const parsed = presentationFromStructuredContent(persisted);
    expect(parsed).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={parsed} />);
    expect(html).toContain('href="https://example.org/news"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('aria-label="Open verified source in a new tab"');
    expect(html).not.toContain("<button");
  });

  it("never makes untrusted URL cells or arbitrary table values actionable", () => {
    const sourceTable = {
      ...data,
      data: {
        columns: [
          { key: "source_url", label: "Source URL" },
          { key: "fact", label: "Fact" },
        ],
        rows: [
          { source_url: "javascript:alert(1)", fact: "https://example.com/value" },
          { source_url: "http://localhost/private", fact: "plain text" },
          { source_url: "https://example.org#fragment", fact: "plain text" },
          { source_url: "https://example.org/ok", fact: "plain text" },
        ],
      },
    };
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={sourceTable} />);
    expect((html.match(/<a /g) ?? []).length).toBe(1);
    expect(html).toContain('href="https://example.org/ok"');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('href="http://localhost');
    expect(html).not.toContain('href="https://example.com/value"');
  });

  it("rejects hostile, malformed and unbounded rows", () => {
    const rejected = [
      { ...data.data, rows: [{ item: "A", fact: "x", private: "secret" }] },
      { ...data.data, rows: [{ item: "A", fact: 3 }] },
      { ...data.data, rows: [] },
      { ...data.data, rows: Array.from({ length: 21 }, () => ({ item: "A", fact: "x" })) },
      { ...data.data, rows: [{ item: "A", fact: "x".repeat(241) }] },
      { ...data.data, rows: [{ item: "A", fact: "bad" + String.fromCharCode(0) }] },
      { ...data.data, columns: [{ key: "item", label: "Item" }, { key: "item", label: "Repeated" }] },
    ];
    for (const value of rejected) {
      expect(parseKarenPresentation({ ...data, data: value })).toBeNull();
    }
  });
});

describe("data table UTF-16 cell parity", () => {
  const base = {
    schema_version: 1, presentation_id: "emoji-table",
    component_type: "data.table", evidence_ref: "verified-receipt",
    data: { columns: [{ key: "fact", label: "Fact" }], rows: [{ fact: "🔎".repeat(120) }] },
  };
  it("accepts 240 UTF-16 units and rejects 242", () => {
    expect(parseKarenPresentation(base)).not.toBeNull();
    expect(parseKarenPresentation({ ...base, data: {
      ...base.data, rows: [{ fact: "🔎".repeat(121) }],
    } })).toBeNull();
  });
});


describe("KCON-770 unsupported media and presentation faults", () => {
  it("test_missing_image_does_not_claim_rendered_media", () => {
    const missing = {
      ...valid, presentation_id: "image-missing",
      component_type: "image.display", data: { url: null, alt: "Unverified" },
    };
    expect(parseKarenPresentation(missing)).toBeNull();
    expect(presentationFromStructuredContent({ presentation: missing })).toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={missing} />);
    expect(html).toContain("Structured presentation unavailable");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("Unverified</");
  });

  it("test_unsupported_presentation_is_not_success", () => {
    const unsupported = {
      ...valid, presentation_id: "unknown-card",
      component_type: "card.arbitrary",
      data: { title: "Unverified success", action: "execute" },
    };
    expect(parseKarenPresentation(unsupported)).toBeNull();
    expect(presentationFromStructuredContent({ presentation: unsupported })).toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={unsupported} />);
    expect(html).toContain("Structured presentation unavailable");
    expect(html).not.toContain("Unverified success");
    expect(html).not.toContain("<button");
  });
});


describe("KGUI-02 governed chart and code host presentation", () => {
  const chart = {
    schema_version: 1, presentation_id: "chart-1",
    component_type: "chart.bar", evidence_ref: "owned:chart",
    data: { title: "Orders", x_label: "Month", y_label: "Count", unit: "items",
      points: [{ label: "Jan", value: 0 }, { label: "Feb", value: 18.5 }] },
  };
  const artifact = {
    schema_version: 1, presentation_id: "code-1",
    component_type: "code.artifact", evidence_ref: "owned:code",
    data: { filename: "analysis.py", language: "python",
      code: "print('<script>alert(1)</script>')\\n" },
  };
  it("renders numeric bars with an accessible source table", () => {
    expect(parseKarenPresentation(chart)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={chart} />);
    expect(html).toContain('data-testid="karen-bar-chart"');
    expect(html).toContain("<table");
    expect(html).toContain("18.5");
    expect(html).toContain("0%");
  });
  it("preserves fractional precision in both labels and accessible source table", () => {
    const precise = { ...chart, data: { ...chart.data, points: [
      { label: "Tiny", value: 0.0001 },
      { label: "Measured", value: 18.56789 },
    ] } };
    expect(parseKarenPresentation(precise)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={precise} />);
    expect((html.match(/0\.0001/g) ?? []).length).toBe(2);
    expect((html.match(/18\.56789/g) ?? []).length).toBe(2);
    expect(html).not.toContain(">18.568<");
    expect(html).not.toContain(">0<");
  });
  it("uses identical UTF-16 bounds for Unicode chart and code metadata", () => {
    const unicodeChart = { ...chart, data: {
      title: "📊".repeat(80), x_label: "📊".repeat(80),
      y_label: "📊".repeat(80), unit: "📊".repeat(16),
      points: [{ label: "📊".repeat(40), value: 0.0001 }],
    } };
    expect(parseKarenPresentation(unicodeChart)).not.toBeNull();
    for (const field of ["title", "x_label", "y_label", "unit"] as const) {
      const excess = field === "unit" ? "📊".repeat(17) : "📊".repeat(81);
      expect(parseKarenPresentation({
        ...unicodeChart, data: { ...unicodeChart.data, [field]: excess },
      })).toBeNull();
    }
    expect(parseKarenPresentation({ ...unicodeChart, data: {
      ...unicodeChart.data, points: [{ label: "📊".repeat(41), value: 0.0001 }],
    } })).toBeNull();

    const unicodeCode = { ...artifact, data: { ...artifact.data, filename: "📊".repeat(80) } };
    expect(parseKarenPresentation(unicodeCode)).not.toBeNull();
    expect(parseKarenPresentation({ ...unicodeCode, data: {
      ...unicodeCode.data, filename: "📊".repeat(81),
    } })).toBeNull();
  });
  it("rejects unverified chart values and action injection", () => {
    for (const value of [NaN, Infinity, -1, 1_000_000_001, true, "12"]) {
      expect(parseKarenPresentation({ ...chart, data: {
        ...chart.data, points: [{ label: "Jan", value }],
      } })).toBeNull();
    }
    expect(parseKarenPresentation({ ...chart, data: {
      ...chart.data, actions: ["delete"], points: chart.data.points,
    } })).toBeNull();
  });
  it("escapes code without allowing execution or UI insertion", () => {
    expect(parseKarenPresentation(artifact)).not.toBeNull();
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={artifact} />);
    expect(html).toContain('data-testid="karen-code-artifact"');
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<button");
    expect(parseKarenPresentation({ ...artifact, data: {
      ...artifact.data, execute: true,
    } })).toBeNull();
    expect(parseKarenPresentation({ ...artifact, data: {
      ...artifact.data, filename: "../secrets.py",
    } })).toBeNull();
  });
});
