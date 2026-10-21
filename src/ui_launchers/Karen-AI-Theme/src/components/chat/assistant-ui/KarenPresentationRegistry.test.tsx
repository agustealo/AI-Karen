import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { KarenPresentationRegistry, parseKarenPresentation, presentationFromStructuredContent } from "./KarenPresentationRegistry";

const valid = {
  schema_version: 1,
  presentation_id: "weather-detroit-1",
  evidence_ref: "tool-weather-result-1",
  component_type: "weather.observation",
  data: { location: "Detroit, Michigan", temperature_f: 60.3, wind_speed_mph: 0.3 },
} as const;

describe("versioned presentation registry", () => {
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
