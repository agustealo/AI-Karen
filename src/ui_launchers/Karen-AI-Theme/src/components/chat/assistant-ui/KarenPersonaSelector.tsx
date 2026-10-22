"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

type PersonaSummary = { id: string; name: string; is_active: boolean };
type PersonaPreferences = { active_persona_id: string | null; show_persona_selector: boolean };

export function KarenPersonaSelector() {
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [preferences, setPreferences] = useState<PersonaPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiClient.get<PersonaSummary[]>("/api/personas/"),
      apiClient.get<PersonaPreferences>("/api/personas/preferences/me"),
    ]).then(([available, current]) => {
      if (cancelled) return;
      setPersonas(available.filter((persona) => persona.is_active));
      setPreferences(current);
      setError(null);
    }).catch(() => {
      if (!cancelled) setError("Persona options are unavailable");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <span role="status" className="text-xs text-muted-foreground">Loading personas…</span>;
  if (!preferences || error && personas.length === 0) {
    return <span role="status" className="text-xs text-muted-foreground">{error || "Persona unavailable"}</span>;
  }
  if (!preferences.show_persona_selector) return null;

  return <div className="flex min-w-0 items-center gap-2">
    <label htmlFor="karen-persona-selector" className="text-xs text-muted-foreground">Persona</label>
    <select id="karen-persona-selector" aria-label="Active Karen persona"
      value={preferences.active_persona_id || ""} disabled={saving}
      onChange={async (event) => {
        const requested = event.target.value || null;
        setSaving(true);
        setError(null);
        try {
          const updated = await apiClient.post<PersonaPreferences>(
            "/api/personas/preferences/switch", { persona_id: requested },
          );
          setPreferences(updated);
        } catch {
          setError("Persona switch failed. Previous selection retained.");
        } finally {
          setSaving(false);
        }
      }}
      className="max-w-44 rounded-lg border border-input bg-background px-2 py-1.5 text-xs">
      <option value="">Karen default</option>
      {personas.map((persona) => <option value={persona.id} key={persona.id}>{persona.name}</option>)}
    </select>
    {saving && <span role="status" className="text-xs text-muted-foreground">Saving…</span>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
  </div>;
}
