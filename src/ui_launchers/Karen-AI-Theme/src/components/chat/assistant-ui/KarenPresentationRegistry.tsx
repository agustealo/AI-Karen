"use client";

/**
 * Allowlisted, versioned read-only presentation envelope for AG-UI data parts.
 * Backend authorization, evidence provenance and persistence remain authoritative.
 */
import { z } from "zod";
import { KarenWeatherPresentation, normalizeWeatherObservation } from "./KarenWeatherPresentation";

const MAX_PRESENTATION_BYTES = 32_768;

const presentationSchema = z.object({
  schema_version: z.literal(1),
  presentation_id: z.string().min(1).max(160),
  component_type: z.enum(["weather.observation", "weather.comparison"]),
  data: z.unknown(),
  evidence_ref: z.string().min(1).max(160),
  correlation_id: z.string().max(160).optional(),
}).strict();

export type KarenPresentationEnvelope = z.infer<typeof presentationSchema>;

export function parseKarenPresentation(value: unknown): KarenPresentationEnvelope | null {
  const result = presentationSchema.safeParse(value);
  if (!result.success) return null;
  // Bound renderer payload size; Zod validates the allowlisted envelope.
  try {
    const serialized = JSON.stringify(value);
    if (!serialized || serialized.length > MAX_PRESENTATION_BYTES) return null;
  } catch {
    return null;
  }
  // Validate each data record; the model may select layout, never invent measurements.
  if (result.data.component_type === "weather.comparison") {
    const items = result.data.data;
    if (!Array.isArray(items) || items.length < 2 || items.length > 5 || !items.every((item) => normalizeWeatherObservation(item))) return null;
    const uniqueLocations = new Set(items.map((item) => normalizeWeatherObservation(item)?.location.toLocaleLowerCase().trim()));
    if (uniqueLocations.size !== items.length) return null;
  } else if (!normalizeWeatherObservation(result.data.data)) return null;
  return result.data;
}

/** Only restore a versioned presentation from backend-owned structured metadata. */
export function presentationFromStructuredContent(value: unknown): KarenPresentationEnvelope | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return parseKarenPresentation((value as Record<string, unknown>).presentation);
}

export function KarenPresentationRegistry({ data }: { data: unknown }) {
  const envelope = parseKarenPresentation(data);
  if (!envelope) {
    return (
      <p role="status" data-testid="karen-presentation-unsupported"
        className="my-2 rounded-lg border border-border/60 px-3 py-2 text-xs text-muted-foreground">
        Structured presentation unavailable. Check the accompanying answer and source details.
      </p>
    );
  }
  switch (envelope.component_type) {
    case "weather.observation":
      return <KarenWeatherPresentation data={envelope.data} />;
    case "weather.comparison":
      return <section aria-label="Weather comparison" data-testid="karen-weather-comparison" className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(envelope.data as unknown[]).map((item, index) => <KarenWeatherPresentation key={index} data={item} />)}
      </section>;
  }
}
