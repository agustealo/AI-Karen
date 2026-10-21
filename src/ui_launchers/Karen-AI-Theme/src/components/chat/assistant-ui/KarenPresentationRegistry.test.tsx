import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { KarenPresentationRegistry, parseKarenPresentation } from "./KarenPresentationRegistry";

const valid = {
  schema_version: 1,
  presentation_id: "weather-detroit-1",
  evidence_ref: "tool-weather-result-1",
  component_type: "weather.observation",
  data: { location: "Detroit, Michigan", temperature_f: 60.3, wind_speed_mph: 0.3 },
} as const;

describe("versioned presentation registry", () => {
  it("renders validated weather evidence", () => {
    expect(parseKarenPresentation(valid)?.presentation_id).toBe("weather-detroit-1");
    const html = renderToStaticMarkup(<KarenPresentationRegistry data={valid} />);
    expect(html).toContain("Detroit");
    expect(html).toContain("0.3");
    expect(html).toContain("mph");
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
