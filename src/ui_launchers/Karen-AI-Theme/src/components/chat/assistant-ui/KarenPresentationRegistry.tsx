"use client";

/**
 * Allowlisted, versioned read-only presentation envelope for AG-UI data parts.
 * Backend authorization, evidence provenance and persistence remain authoritative.
 */
import { z } from "zod";
import { KarenWeatherPresentation, normalizeWeatherObservation } from "./KarenWeatherPresentation";

const presentationSchema = z.object({
  schema_version: z.literal(1),
  presentation_id: z.string().min(1).max(160),
  component_type: z.literal("weather.observation"),
  data: z.unknown(),
  correlation_id: z.string().max(160).optional(),
}).strict();

export type KarenPresentationEnvelope = z.infer<typeof presentationSchema>;

export function parseKarenPresentation(value: unknown): KarenPresentationEnvelope | null {
  const result = presentationSchema.safeParse(value);
  if (!result.success) return null;
  // Never permit a typed card unless its underlying factual payload validates.
  if (!normalizeWeatherObservation(result.data)) return null;
  return result.data;
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
  }
}
