"use client";

/**
 * Evidence-grounded weather presentation shared by AG-UI data parts and tool results.
 * This component has no execution authority and deliberately never fetches data.
 */
import { Cloud, CloudDrizzle, CloudFog, CloudRain, CloudSnow, CloudSun, Droplets, Sun, Wind } from "lucide-react";
import type { ReactNode } from "react";

type WeatherFields = Record<string, unknown>;
export type WeatherObservation = {
  location: string;
  observedAt: string | null;
  timezone: string | null;
  temperatureF: number;
  highF: number | null;
  lowF: number | null;
  humidity: number | null;
  windMph: number | null;
  precipitationProbability: number | null;
  weatherCode: number | null;
  provider: string | null;
  sourceUrl: string | null;
};

const CONDITIONS: Record<number, { label: string; icon: typeof Sun }> = {
  0: { label: "Clear sky", icon: Sun },
  1: { label: "Mainly clear", icon: Sun },
  2: { label: "Partly cloudy", icon: CloudSun },
  3: { label: "Overcast", icon: Cloud },
  45: { label: "Fog", icon: CloudFog },
  48: { label: "Depositing rime fog", icon: CloudFog },
  51: { label: "Light drizzle", icon: CloudDrizzle },
  53: { label: "Drizzle", icon: CloudDrizzle },
  55: { label: "Dense drizzle", icon: CloudDrizzle },
  56: { label: "Freezing drizzle", icon: CloudDrizzle },
  57: { label: "Dense freezing drizzle", icon: CloudDrizzle },
  61: { label: "Light rain", icon: CloudRain },
  63: { label: "Rain", icon: CloudRain },
  65: { label: "Heavy rain", icon: CloudRain },
  66: { label: "Freezing rain", icon: CloudRain },
  67: { label: "Heavy freezing rain", icon: CloudRain },
  71: { label: "Light snow", icon: CloudSnow },
  73: { label: "Snow", icon: CloudSnow },
  75: { label: "Heavy snow", icon: CloudSnow },
  77: { label: "Snow grains", icon: CloudSnow },
  80: { label: "Light rain showers", icon: CloudRain },
  81: { label: "Rain showers", icon: CloudRain },
  82: { label: "Violent rain showers", icon: CloudRain },
  85: { label: "Snow showers", icon: CloudSnow },
  86: { label: "Heavy snow showers", icon: CloudSnow },
  95: { label: "Thunderstorm", icon: CloudRain },
  96: { label: "Thunderstorm with hail", icon: CloudRain },
  99: { label: "Severe thunderstorm with hail", icon: CloudRain },
};

function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && /^-?\d+(?:\.\d+)?(?:\s*°?\s*F|\s*%|\s*mph)?$/i.test(value.trim())) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function numberFrom(record: WeatherFields, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = numeric(record[key]);
    if (value !== null) return value;
  }
  return null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function unwrap(value: unknown): WeatherFields | null {
  if (typeof value === "string") {
    try { return unwrap(JSON.parse(value)); } catch { return null; }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const obj = value as WeatherFields;
  for (const key of ["extractedData", "extracted_data", "observation", "result", "data"]) {
    if (obj[key] && obj[key] !== value) {
      const nested = unwrap(obj[key]);
      if (nested && (nested.temperature_f !== undefined || nested.temperature !== undefined)) return nested;
    }
  }
  return obj;
}

export function normalizeWeatherObservation(value: unknown): WeatherObservation | null {
  const data = unwrap(value);
  if (!data) return null;
  const location = optionalString(data.location);
  const temperatureF = numberFrom(data, "temperature_f", "temperatureF", "temperature");
  if (!location || temperatureF === null || temperatureF < -150 || temperatureF > 150) return null;
  const percentage = (...keys: string[]) => {
    const n = numberFrom(data, ...keys);
    return n !== null && n >= 0 && n <= 100 ? n : null;
  };
  const range = (...keys: string[]) => {
    const n = numberFrom(data, ...keys);
    return n !== null && n >= -150 && n <= 150 ? n : null;
  };
  const wind = numberFrom(data, "wind_speed_mph", "windMph");
  const weatherCode = numberFrom(data, "weather_code", "weatherCode");
  const source = optionalString(data.source_url);
  let sourceUrl: string | null = null;
  if (source) {
    try {
      const parsed = new URL(source);
      if (parsed.protocol === "https:" && parsed.hostname === "api.open-meteo.com") sourceUrl = parsed.href;
    } catch { /* Keep source label but never link an untrusted URL. */ }
  }
  return {
    location,
    observedAt: optionalString(data.observed_at),
    timezone: optionalString(data.timezone),
    temperatureF,
    highF: range("high_f", "high"),
    lowF: range("low_f", "low"),
    humidity: percentage("humidity"),
    windMph: wind !== null && wind >= 0 && wind <= 300 ? wind : null,
    precipitationProbability: percentage("precipitation_probability"),
    weatherCode: weatherCode !== null && Number.isInteger(weatherCode) ? weatherCode : null,
    provider: optionalString(data.provider),
    sourceUrl,
  };
}

function formatObserved(observation: WeatherObservation): string | null {
  if (!observation.observedAt) return null;
  // An offset-less timestamp is local to the provider's reported location, not UTC.
  const local = observation.observedAt.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (!local) return observation.observedAt;
  const [, date, time] = local;
  return `${date} ${time} local${observation.timezone ? ` (${observation.timezone})` : ""}`;
}

function Metric({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="rounded-lg border border-border/50 bg-muted/25 p-3">
    <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">{icon}<span>{title}</span></div>
    <div className="font-semibold tabular-nums">{children}</div>
  </div>;
}

export function KarenWeatherPresentation({ data }: { data: unknown }) {
  const weather = normalizeWeatherObservation(data);
  if (!weather) return null;
  const condition = weather.weatherCode === null ? null : CONDITIONS[weather.weatherCode] ?? null;
  const ConditionIcon = condition?.icon;
  const degrees = (value: number) => `${value.toFixed(1)}°F`;
  const hasDetails = weather.humidity !== null || weather.windMph !== null || weather.precipitationProbability !== null;
  return (
    <section aria-label={`Weather observation for ${weather.location}`} data-testid="karen-weather-presentation"
      className="my-3 min-w-0 space-y-3 rounded-2xl border border-border/70 bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{weather.location}</h3>
          {formatObserved(weather) && <p className="text-xs text-muted-foreground">Observed {formatObserved(weather)}</p>}
        </div>
        {condition && <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {ConditionIcon && <ConditionIcon className="h-6 w-6" aria-hidden="true"/>}
          <span>{condition.label}</span>
        </div>}
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="text-4xl font-semibold tracking-tight tabular-nums">{degrees(weather.temperatureF)}</div>
        {(weather.highF !== null || weather.lowF !== null) && <p className="text-sm text-muted-foreground">
          {weather.highF !== null ? `High ${degrees(weather.highF)}` : ""}
          {weather.highF !== null && weather.lowF !== null ? " · " : ""}
          {weather.lowF !== null ? `Low ${degrees(weather.lowF)}` : ""}
        </p>}
      </div>
      {hasDetails && <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {weather.humidity !== null && <Metric icon={<Droplets className="h-4 w-4" aria-hidden="true"/>} title="Humidity">{weather.humidity}%</Metric>}
        {weather.windMph !== null && <Metric icon={<Wind className="h-4 w-4" aria-hidden="true"/>} title="Wind speed">{weather.windMph} mph</Metric>}
        {weather.precipitationProbability !== null && <Metric icon={<CloudRain className="h-4 w-4" aria-hidden="true"/>} title="Precipitation chance">{weather.precipitationProbability}%</Metric>}
      </div>}
      <p className="break-words text-xs text-muted-foreground">
        {weather.provider ? `Source: ${weather.provider}` : "Source: weather capability"}
        {weather.sourceUrl && <> · <a href={weather.sourceUrl} target="_blank" rel="noopener noreferrer" className="underline">Provider endpoint</a></>}
        {" · Values reported by the tool, not independently refreshed."}
      </p>
    </section>
  );
}
