"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient, ApiError } from "@/lib/api";

type PersonaSummary = { id: string; name: string; is_active: boolean };
type PersonaPreferences = {
  revision: number;
  active_persona_id: string | null;
  show_persona_selector: boolean;
};

function validPreferences(value: unknown): value is PersonaPreferences {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return Number.isSafeInteger(record.revision) &&
    (record.revision as number) >= 0 &&
    (record.active_persona_id === null ||
      typeof record.active_persona_id === "string") &&
    typeof record.show_persona_selector === "boolean";
}

/**
 * Shared footer for both chat surfaces. Persona Studio already uses the
 * canonical revision-fenced preferences endpoint. Reuse it here rather
 * than sending an unconditional switch that can overwrite a newer tab.
 */
export function KarenPersonaSelector({
  onStartNewConversation,
}: {
  /** Canonical SessionProvider action; never fabricate a client-only thread. */
  onStartNewConversation?: () => Promise<void>;
} = {}) {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [preferences, setPreferences] = useState<PersonaPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switchConfirmed, setSwitchConfirmed] = useState(false);
  const [startingConversation, setStartingConversation] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiClient.get<PersonaSummary[]>("/api/personas/"),
      apiClient.get<PersonaPreferences>("/api/personas/preferences/me"),
    ]).then(([available, current]) => {
      if (cancelled) return;
      if (!Array.isArray(available) || !validPreferences(current)) {
        throw new Error("Invalid persona catalog response");
      }
      setPersonas(available.filter((persona) =>
        persona && typeof persona.id === "string" &&
        typeof persona.name === "string" && persona.is_active));
      setPreferences(current);
      setError(null);
    }).catch(() => {
      if (!cancelled) setError("Persona options are unavailable");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const reloadCurrent = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const current: unknown = await apiClient.get<PersonaPreferences>(
        "/api/personas/preferences/me",
      );
      if (!validPreferences(current)) throw new Error("Invalid preference receipt");
      if (mounted.current) {
        setPreferences(current);
        setStale(false);
        setSwitchConfirmed(false);
      }
    } catch {
      if (mounted.current) setError("Persona selection could not be reloaded.");
    } finally {
      if (mounted.current) setSaving(false);
    }
  };

  if (loading) return <span role="status" className="text-xs text-muted-foreground">Loading personas…</span>;
  if (!preferences || error && personas.length === 0) {
    return <span role="status" className="text-xs text-muted-foreground">{error || "Persona unavailable"}</span>;
  }
  if (!preferences.show_persona_selector) return null;

  return <div className="flex min-w-0 items-center gap-2">
    <label htmlFor="karen-persona-selector" className="text-xs text-muted-foreground">Persona</label>
    <select id="karen-persona-selector" aria-label="Active Karen persona"
      value={preferences.active_persona_id || ""} disabled={saving || stale}
      onChange={async (event) => {
        if (saving || stale) return;
        const requested = event.target.value || null;
        if (requested === preferences.active_persona_id) return;
        setSaving(true);
        setError(null);
        try {
          const updated: unknown = await apiClient.put<PersonaPreferences>(
            "/api/personas/preferences/me",
            { active_persona_id: requested, expected_revision: preferences.revision },
          );
          if (!validPreferences(updated) ||
              updated.revision !== preferences.revision + 1 ||
              updated.active_persona_id !== requested) {
            throw new Error("Persona switch receipt not confirmed");
          }
          if (mounted.current) {
            setPreferences(updated);
            setSwitchConfirmed(true);
          }
        } catch (cause: unknown) {
          if (mounted.current) {
            if (cause instanceof ApiError && cause.status === 409) {
              setStale(true);
              setError("Persona changed in another window. Reload the current selection.");
            } else {
              setError("Persona switch failed. Previous selection retained.");
            }
          }
        } finally {
          if (mounted.current) setSaving(false);
        }
      }}
      className="max-w-44 rounded-lg border border-input bg-background px-2 py-1.5 text-xs">
      <option value="">Karen default</option>
      {personas.map((persona) => <option value={persona.id} key={persona.id}>{persona.name}</option>)}
    </select>
    {saving && <span role="status" className="text-xs text-muted-foreground">Saving…</span>}
    {switchConfirmed && <span role="status" className="text-xs text-muted-foreground">
      Persona selection saved. To keep conversations separate, start a new thread before sending.
    </span>}
    {switchConfirmed && onStartNewConversation && <button type="button"
      disabled={startingConversation || saving}
      aria-label="Start new conversation for selected persona"
      onClick={async () => {
        if (startingConversation || saving) return;
        setStartingConversation(true);
        setError(null);
        try {
          await onStartNewConversation();
          if (mounted.current) setSwitchConfirmed(false);
        } catch {
          if (mounted.current) {
            setError("Unable to create a new conversation. The current thread was not changed.");
          }
        } finally {
          if (mounted.current) setStartingConversation(false);
        }
      }}
      className="rounded-md border border-input px-2 py-1.5 text-xs hover:bg-muted disabled:opacity-50">
      {startingConversation ? "Creating conversation…" : "New conversation"}
    </button>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
    {stale && <button type="button" disabled={saving} onClick={() => void reloadCurrent()}
      className="rounded-md border border-input px-2 py-1.5 text-xs">
      Reload current persona
    </button>}
  </div>;
}
