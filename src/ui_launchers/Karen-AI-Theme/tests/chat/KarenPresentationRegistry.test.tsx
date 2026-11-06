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
  it("rejects hostile, malformed and unbounded rows", () => {
    const rejected = [
      { ...data.data, rows: [{ item: "A", fact: "x", private: "secret" }] },
      { ...data.data, rows: [{ item: "A", fact: 3 }] },
      { ...data.data, rows: [] },
      { ...data.data, rows: Array.from({ length: 21 }, () => ({ item: "A", fact: "x" })) },
      { ...data.data, rows: [{ item: "A", fact: "x".repeat(241) }] },
      { ...data.data, rows: [{ item: "A", fact: "bad\\u0000" }] },
      { ...data.data, columns: [{ key: "item", label: "Item" }, { key: "item", label: "Repeated" }] },
    ];
    for (const value of rejected) {
      expect(parseKarenPresentation({ ...data, data: value })).toBeNull();
    }
  });
});
