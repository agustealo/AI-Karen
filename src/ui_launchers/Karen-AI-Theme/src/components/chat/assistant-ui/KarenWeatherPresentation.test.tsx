import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { KarenWeatherPresentation, normalizeWeatherObservation } from "./KarenWeatherPresentation";

const observation = {
  location: "Detroit, Michigan, US",
  observed_at: "2026-10-21T12:45",
  timezone: "America/Detroit",
  temperature: "60.3 °F",
  temperature_f: 60.3,
  provider: "open_meteo",
  source_url: "https://api.open-meteo.com/v1/forecast",
  weather_code: 1,
  humidity: 70,
  wind_speed_mph: 0.3,
  high_f: 66.4,
  low_f: 41.1,
  precipitation_probability: 0,
};

describe("governed weather presentation", () => {
  it("preserves all relevant measurements, condition, source and observation timestamp", () => {
    const html = renderToStaticMarkup(<KarenWeatherPresentation data={{ extractedData: observation }} />);
    for (const required of ["Detroit", "60.3°F", "66.4°F", "41.1°F", "70%", "0.3", "mph", "0%", "Mainly clear", "America/Detroit", "open_meteo"]) {
      expect(html).toContain(required);
    }
  });

  it("handles missing optional fields without inventing values", () => {
    const html = renderToStaticMarkup(<KarenWeatherPresentation data={{ location: "NYC", temperature_f: 58 }} />);
    expect(html).toContain("58.0°F");
    expect(html).not.toContain("Humidity");
    expect(html).not.toContain("Wind speed");
    expect(html).not.toContain("Precipitation chance");
  });

  it("renders MCP and AG-UI structuredContent tool results", () => {
    const result = { content: [{ type: "text", text: "Weather retrieved" }], structuredContent: observation };
    expect(normalizeWeatherObservation(result)?.windMph).toBe(0.3);
    expect(renderToStaticMarkup(<KarenWeatherPresentation data={result} />)).toContain("Mainly clear");
  });

  it("rejects invalid and unrelated tool results", () => {
    expect(normalizeWeatherObservation({ location: "Detroit", temperature_f: "NaN" })).toBeNull();
    expect(normalizeWeatherObservation({ location: "Detroit", temperature_f: 9999 })).toBeNull();
    expect(normalizeWeatherObservation({ result: { status: "complete" } })).toBeNull();
  });

  it("does not emit hostile URLs as clickable sources", () => {
    const html = renderToStaticMarkup(
      <KarenWeatherPresentation data={{ ...observation, source_url: "javascript:alert(1)" }} />,
    );
    expect(html).not.toContain("href=");
    expect(html).not.toContain("javascript:");
  });


  it("accepts explicit Fahrenheit and rejects unlabelled numeric temperatures", () => {
    expect(normalizeWeatherObservation({ location: "Detroit", temperature: "60.3 °F" })?.temperatureF).toBe(60.3);
    expect(normalizeWeatherObservation({ location: "Detroit", temperature: 60.3 })).toBeNull();
  });

  it("bounds nested and recursive serialized envelopes", () => {
    let data: unknown = { location: "Detroit", temperature_f: 60.3 };
    for (let i = 0; i < 9; i += 1) data = { result: data };
    expect(normalizeWeatherObservation(data)).toBeNull();
  });

  it("does not fabricate conditions for unknown weather codes", () => {
    const html = renderToStaticMarkup(
      <KarenWeatherPresentation data={{ ...observation, weather_code: 500 }} />,
    );
    expect(html).not.toContain("Mainly clear");
    expect(html).toContain("60.3°F");
  });
});
