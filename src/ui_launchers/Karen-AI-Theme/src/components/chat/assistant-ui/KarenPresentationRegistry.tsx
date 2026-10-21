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
  component_type: z.enum(["weather.observation", "weather.comparison", "planner.task_list"]),
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
  if (result.data.component_type === "planner.task_list") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const tasks = (value as Record<string, unknown>).tasks;
    if (!Array.isArray(tasks) || tasks.length < 1 || tasks.length > 20 || !tasks.every((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.id === "string" && item.id.length > 0 && item.id.length <= 160 && typeof item.title === "string" && item.title.trim().length > 0 && item.title.length <= 240 && ["todo", "in_progress", "completed", "blocked"].includes(item.status))) return null;
  } else if (result.data.component_type === "weather.comparison") {
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
    case "planner.task_list": {
      const tasks = (envelope.data as { tasks: { id: string; title: string; status: string }[] }).tasks;
      return <section aria-label="Planner tasks" data-testid="karen-planner-task-list" className="my-3 rounded-xl border border-border/70 p-4">
        <h3 className="mb-3 font-semibold">Planner tasks</h3>
        <ul className="space-y-2">{tasks.map((task) => <li key={task.id} className="flex items-start justify-between gap-3 text-sm"><span className="min-w-0 break-words">{task.title}</span><span className="shrink-0 text-xs text-muted-foreground">{task.status.replace("_", " ")}</span></li>)}</ul>
      </section>;
    }
    case "weather.observation":
      return <KarenWeatherPresentation data={envelope.data} />;
    case "weather.comparison":
      return <section aria-label="Weather comparison" data-testid="karen-weather-comparison" className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(envelope.data as unknown[]).map((item, index) => <KarenWeatherPresentation key={index} data={item} />)}
      </section>;
  }
}
