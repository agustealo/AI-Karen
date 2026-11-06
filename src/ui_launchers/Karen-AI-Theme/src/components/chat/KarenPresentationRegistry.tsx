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
  component_type: z.enum(["weather.observation", "weather.comparison", "planner.task_list", "time.observation", "date.observation", "surface.composition", "search.results", "data.table"]),
  data: z.unknown(),
  evidence_ref: z.string().min(1).max(160),
  correlation_id: z.string().max(160).optional(),
  display: z.object({ density: z.enum(["compact", "comfortable"]) }).strict().optional(),
}).strict();

/**
 * Improve clock readability without changing the observed instant or
 * assigning a timezone that the backend has not verified.
 */
export function displayClockObservation(formatted: string): { time: string; date?: string } {
  const match = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$/.exec(formatted.trim());
  if (!match) return { time: formatted };
  const hour = Number(match[4]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (hour > 23 || month < 1 || month > 12 || day < 1 || day > 31 ||
      Number(match[5]) > 59 || (match[6] && Number(match[6]) > 59)) return { time: formatted };
  const displayHour = hour % 12 || 12;
  return { time: `${displayHour}:${match[5]} ${hour < 12 ? "AM" : "PM"}`, date: `${match[1]}-${match[2]}-${match[3]}` };
}

/**
 * Source links are rendered, never fetched or executed by this component.
 * Guard link schemes and local-network destinations independently of the
 * backend's canonical evidence validator.
 */
function isPublicSourceUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value || value.length > 1200 ||
      /[\s\u0000-\u001f\\]/.test(value)) return false;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    if (!["http:", "https:"].includes(parsed.protocol) ||
        parsed.username || parsed.password || parsed.port === "0" || parsed.hash ||
        !/^[a-z0-9.-]+$/.test(host)) return false;
    // Mirror the backend's DNS-only rule. Reject numeric hosts and URL
    // parser aliases for loopback/private network IP addresses.
    const labels = host.split(".");
    return labels.length >= 2 && labels.every((label) =>
      label.length > 0 && label.length <= 63 &&
      !label.startsWith("-") && !label.endsWith("-") &&
      /^[a-z0-9-]+$/.test(label)) &&
      /[a-z]/.test(labels[labels.length - 1]) &&
      host !== "localhost" && !/\.(localhost|local|internal)$/.test(host);
  } catch {
    return false;
  }
}

export type KarenPresentationEnvelope = z.infer<typeof presentationSchema>;

export function parseKarenPresentation(value: unknown): KarenPresentationEnvelope | null {
  const result = presentationSchema.safeParse(value);
  if (!result.success) return null;
  // Bound renderer payload size; Zod validates the allowlisted envelope.
  try {
    const serialized = JSON.stringify(value);
    if (!serialized || new TextEncoder().encode(serialized).byteLength > MAX_PRESENTATION_BYTES) return null;
  } catch {
    return null;
  }
  // Validate each data record; the model may select layout, never invent measurements.
  if (result.data.component_type === "surface.composition") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const data = value as Record<string, unknown>;
    const keys = Object.keys(data).sort().join(",");
    if (keys !== "items,layout" && keys !== "evidence_refs,items,layout") return null;
    const manifest = data.evidence_refs;
    if (manifest !== undefined && (!Array.isArray(manifest) || manifest.length < 1 ||
        manifest.length > 6 || manifest.some((ref) => typeof ref !== "string" || !ref.length || ref.length > 160) ||
        new Set(manifest).size !== manifest.length)) return null;
    if (data.layout !== "stack" && data.layout !== "grid") return null;
    if (!Array.isArray(data.items) || data.items.length < 1 || data.items.length > 6) return null;
    for (const item of data.items) {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const child = item as Record<string, unknown>;
      if (child.component_type === "surface.composition" ||
          (manifest === undefined ? child.evidence_ref !== result.data.evidence_ref : !manifest.includes(child.evidence_ref)) ||
          !parseKarenPresentation(child)) return null;
    }
    if (Array.isArray(manifest) && new Set(data.items.map((item: Record<string, unknown>) => item.evidence_ref)).size !== manifest.length) return null;
  } else if (result.data.component_type === "date.observation") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const date = (value as Record<string, unknown>).formatted;
    const timezone = (value as Record<string, unknown>).timezone;
    if (typeof date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
    const observed = new Date(date + "T00:00:00Z");
    if (Number.isNaN(observed.valueOf()) || observed.toISOString().slice(0, 10) !== date) return null;
    if (timezone !== undefined && (typeof timezone !== "string" || !timezone || timezone.length > 100)) return null;
    if (Object.keys(value).some((key) => !["formatted", "timezone"].includes(key))) return null;
  } else if (result.data.component_type === "time.observation") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const clock = (value as Record<string, unknown>).formatted;
    const timezone = (value as Record<string, unknown>).timezone;
    if (typeof clock !== "string" || !clock.trim() || clock.length > 160) return null;
    if (timezone !== undefined && (typeof timezone !== "string" || timezone.length > 100)) return null;
    if (Object.keys(value).some((key) => !["formatted", "timezone"].includes(key))) return null;
  } else if (result.data.component_type === "data.table") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const record = value as Record<string, unknown>;
    if (Object.keys(record).some((key) => !["title", "columns", "rows"].includes(key)) ||
        !Array.isArray(record.columns) || !Array.isArray(record.rows) ||
        record.columns.length < 1 || record.columns.length > 6 ||
        record.rows.length < 1 || record.rows.length > 20 ||
        (record.title !== undefined && (typeof record.title !== "string" ||
          !record.title.trim() || record.title.trim().length > 160))) return null;
    const columns = record.columns as Record<string, unknown>[];
    if (!columns.every((column) => column && typeof column === "object" &&
      !Array.isArray(column) && Object.keys(column).sort().join(",") === "key,label" &&
      typeof column.key === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(column.key) &&
      typeof column.label === "string" && !!column.label.trim() &&
      column.label.trim().length <= 80)) return null;
    const keys = columns.map((column) => column.key as string);
    if (new Set(keys).size !== keys.length) return null;
    const expected = [...keys].sort().join(",");
    for (const row of record.rows) {
      if (!row || typeof row !== "object" || Array.isArray(row) ||
          Object.keys(row).sort().join(",") !== expected) return null;
      for (const key of keys) {
        const cell = (row as Record<string, unknown>)[key];
        if (cell !== null && (typeof cell !== "string" || cell.length > 240 ||
          /[\\u0000-\\u0008\\u000b-\\u001f]/.test(cell))) return null;
      }
    }
  } else if (result.data.component_type === "search.results") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const record = value as Record<string, unknown>;
    if (Object.keys(record).length !== 1 || !Array.isArray(record.results) ||
        record.results.length < 1 || record.results.length > 5) return null;
    const seen = new Set<string>();
    for (const rawItem of record.results) {
      if (!rawItem || typeof rawItem !== "object" || Array.isArray(rawItem)) return null;
      const item = rawItem as Record<string, unknown>;
      if (Object.keys(item).some((key) => !["url", "title", "snippet", "published_at"].includes(key)) ||
          !isPublicSourceUrl(item.url) || seen.has(item.url) ||
          typeof item.snippet !== "string" || !item.snippet.trim() ||
          item.snippet.trim().length > 600 ||
          (item.title !== undefined && (typeof item.title !== "string" ||
            !item.title.trim() || item.title.trim().length > 200)) ||
          (item.published_at !== undefined && (typeof item.published_at !== "string" ||
            !item.published_at.trim() || item.published_at.trim().length > 80))) return null;
      seen.add(item.url);
    }
  } else if (result.data.component_type === "planner.task_list") {
    const value = result.data.data;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const tasks = (value as Record<string, unknown>).tasks;
    if (!Array.isArray(tasks) || tasks.length < 1 || tasks.length > 20 || !tasks.every((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.id === "string" && item.id.length > 0 && item.id.length <= 160 && typeof item.title === "string" && item.title.trim().length > 0 && item.title.length <= 240 && ["todo", "in_progress", "completed", "cancelled"].includes(item.status))) return null;
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
    case "surface.composition": {
      const composite = envelope.data as { layout: "stack" | "grid"; items: KarenPresentationEnvelope[] };
      return <section aria-label="Generated information surface" data-testid="karen-composed-surface"
        className={composite.layout === "grid" ? "my-3 grid grid-cols-1 gap-3 lg:grid-cols-2" : "my-3 flex flex-col gap-3"}>
        {composite.items.map((item) =>
          <KarenPresentationRegistry key={item.presentation_id} data={item} />)}
      </section>;
    }
    case "date.observation": {
      const observed = envelope.data as { formatted: string; timezone?: string };
      const calendarDate = new Date(observed.formatted + "T00:00:00Z");
      const label = new Intl.DateTimeFormat("en-US", {
        weekday: "long", year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
      }).format(calendarDate);
      return <section aria-label="Verified date observation" data-testid="karen-date-presentation"
        className={envelope.display?.density === "compact" ? "my-2 rounded-lg border border-border/70 p-2" : "my-3 rounded-xl border border-border/70 p-4"}>
        <p className="text-xs font-medium text-muted-foreground">Reported date{observed.timezone ? ` (${observed.timezone})` : ""}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{label}</p>
        <p className="mt-1 text-xs text-muted-foreground">{observed.formatted}</p>
      </section>;
    }
    case "time.observation": {
      const clock = envelope.data as { formatted: string; timezone?: string };
      const display = displayClockObservation(clock.formatted);
      return <section aria-label="Verified time observation" data-testid="karen-time-presentation"
        className={envelope.display?.density === "compact" ? "my-2 rounded-lg border border-border/70 p-2" : "my-3 rounded-xl border border-border/70 p-4"}>
        <p className="text-xs font-medium text-muted-foreground">Reported time{clock.timezone ? ` (${clock.timezone})` : ""}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{display.time}</p>
        {display.date && <p className="mt-1 text-xs text-muted-foreground">{display.date}</p>}
        {clock.timezone && <p className="mt-1 text-xs text-muted-foreground">{clock.timezone}</p>}
      </section>;
    }
    case "data.table": {
      const table = envelope.data as {
        title?: string;
        columns: { key: string; label: string }[];
        rows: Record<string, string | null>[];
      };
      return <section aria-label={table.title || "Verified data table"}
        data-testid="karen-data-table" className="my-3 min-w-0 rounded-xl border border-border/70 p-3">
        {table.title && <h3 className="mb-3 font-semibold">{table.title}</h3>}
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead><tr>{table.columns.map((column) =>
              <th scope="col" key={column.key} className="border-b border-border/70 px-3 py-2 font-semibold">
                {column.label}
              </th>)}</tr></thead>
            <tbody>{table.rows.map((row, index) =>
              <tr key={index}>{table.columns.map((column) =>
                <td key={column.key} className="border-b border-border/50 px-3 py-2 align-top whitespace-pre-wrap break-words">
                  {row[column.key] === null ? <span className="text-muted-foreground">Not provided</span> : row[column.key]}
                </td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>;
    }
    case "search.results": {
      const entries = (envelope.data as { results: {
        url: string; title?: string; snippet: string; published_at?: string;
      }[] }).results;
      return <section aria-label="Verified web search results"
        data-testid="karen-search-results" className="my-3 flex flex-col gap-3">
        {entries.map((entry) => (
          <article key={entry.url} className="min-w-0 rounded-xl border border-border/70 p-4">
            <h3 className="font-semibold">{entry.title || "Source result"}</h3>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm">{entry.snippet}</p>
            {entry.published_at && <p className="mt-2 text-xs text-muted-foreground">
              Published (source-reported): {entry.published_at}
            </p>}
            <a href={entry.url} target="_blank" rel="noopener noreferrer"
              className="mt-2 inline-block break-all text-sm underline underline-offset-2">
              View source: {new URL(entry.url).hostname}
            </a>
          </article>
        ))}
      </section>;
    }
    case "planner.task_list": {
      const tasks = (envelope.data as { tasks: { id: string; title: string; status: string }[] }).tasks;
      return <section aria-label="Planner tasks" data-testid="karen-planner-task-list" className="my-3 rounded-xl border border-border/70 p-4">
        <h3 className="mb-3 font-semibold">Planner tasks</h3>
        <ul className="space-y-2">{tasks.map((task) => <li key={task.id} className="flex items-start justify-between gap-3 text-sm"><span className="min-w-0 break-words">{task.title}</span><span className="shrink-0 text-xs text-muted-foreground">{task.status.replace("_", " ")}</span></li>)}</ul>
      </section>;
    }
    case "weather.observation":
      return <KarenWeatherPresentation data={envelope.data} density={envelope.display?.density} />;
    case "weather.comparison":
      return <section aria-label="Weather comparison" data-testid="karen-weather-comparison" className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(envelope.data as unknown[]).map((item, index) => <KarenWeatherPresentation key={index} data={item} />)}
      </section>;
  }
}
