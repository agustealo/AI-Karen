"use client";

/**
 * Inert Card Studio layout editor.
 *
 * The preview never binds evidence or calls KarenPresentationRegistry: doing
 * so without a runtime-authorized evidence receipt would fake live data.
 * Only the host's catalog types are selectable. The backend owns identity,
 * policy, RLS and committed revisions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import { Archive, ArrowDown, ArrowUp, GripVertical, Plus, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/useAuth";
import {
  ApiError,
  cardDefinitionSchema,
  cardStudioErrorMessage,
  createBlankCardDraft,
  listCardStudioCatalog,
  listSavedCardTemplates,
  submitCardMutation,
  validateCardDefinition,
  type CardDefinition,
  type CardMutation,
  type CatalogEntry,
  type SavedCardTemplate,
} from "@/lib/card-studio-api";

type Readiness = "loading" | "ready" | "unavailable" | "failed";

function storageKey(tenant: string, user: string): string {
  return `karen.cardstudio.unverified.v1:${JSON.stringify([tenant, user])}`;
}

function recoverPending(key: string): CardMutation | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const item = value as Record<string, unknown>;
    if (typeof item.idempotency_key !== "string" ||
        !/^[a-f0-9-]{36}$/i.test(item.idempotency_key)) return null;
    if (item.operation === "create") {
      const parsed = cardDefinitionSchema.safeParse(item.draft);
      if (parsed.success) return {
        operation: "create",
        idempotency_key: item.idempotency_key,
        draft: parsed.data,
      };
    }
    if (item.operation === "revise" && typeof item.template_id === "string" &&
        Number.isSafeInteger(item.expected_revision) && Number(item.expected_revision) > 0) {
      const parsed = cardDefinitionSchema.safeParse(item.draft);
      if (parsed.success) return {
        operation: "revise",
        idempotency_key: item.idempotency_key,
        template_id: item.template_id,
        expected_revision: Number(item.expected_revision),
        draft: parsed.data,
      };
    }
    if (item.operation === "archive" && typeof item.template_id === "string" &&
        Number.isSafeInteger(item.expected_revision) && Number(item.expected_revision) > 0) {
      return {
        operation: "archive",
        idempotency_key: item.idempotency_key,
        template_id: item.template_id,
        expected_revision: Number(item.expected_revision),
      };
    }
    return null;
  } catch {
    return null;
  }
}

function rememberPending(key: string, request: CardMutation | null): boolean {
  try {
    if (request) window.sessionStorage.setItem(key, JSON.stringify(request));
    else window.sessionStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function labelForComponent(component: string): string {
  return component.replace(/[._]/g, " ").replace(/\b\w/g, match => match.toUpperCase());
}

function nextSlotId(slots: CardDefinition["slots"]): string {
  let index = 1;
  while (slots.some(slot => slot.slot_id === `slot_${index}`)) index += 1;
  return `slot_${index}`;
}

function insertOrReplace(
  current: readonly SavedCardTemplate[],
  saved: SavedCardTemplate,
): SavedCardTemplate[] {
  return [saved, ...current.filter(item => item.template_id !== saved.template_id)]
    .sort((a, b) => a.template_key.localeCompare(b.template_key));
}

export function CardStudioWorkspace() {
  const { user } = useAuth();
  const principal = user?.tenant_id && user?.user_id
    ? storageKey(user.tenant_id, user.user_id)
    : null;
  const [readiness, setReadiness] = useState<Readiness>("loading");
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [templates, setTemplates] = useState<SavedCardTemplate[]>([]);
  const [selected, setSelected] = useState<SavedCardTemplate | null>(null);
  const [draft, setDraft] = useState<CardDefinition | null>(null);
  const [pending, setPending] = useState<CardMutation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [draggedSlot, setDraggedSlot] = useState<string | null>(null);

  const load = useCallback(async (signal?: { active: boolean }) => {
    if (!principal) return;
    setReadiness("loading");
    setError("");
    try {
      const [available, saved] = await Promise.all([
        listCardStudioCatalog(),
        listSavedCardTemplates(),
      ]);
      if (signal && !signal.active) return;
      const ownedTypes = new Set(available.flatMap(item =>
        item.definition.slots.map(slot => slot.component_type),
      ));
      const valid = saved.filter(item =>
        item.definition.slots.every(slot => ownedTypes.has(slot.component_type)),
      );
      setCatalog(available);
      setTemplates(valid);
      const recovered = recoverPending(principal);
      setPending(recovered);
      if (recovered) {
        if (recovered.operation !== "archive") {
          setDraft(recovered.draft);
        }
        setMessage("An earlier save has an unverified outcome. Replay the identical request to resolve it.");
      } else {
        setDraft(current => current ?? createBlankCardDraft(available));
      }
      setReadiness("ready");
    } catch (cause) {
      if (signal && !signal.active) return;
      setReadiness(cause instanceof ApiError && cause.status === 404
        ? "unavailable" : "failed");
      setError(cardStudioErrorMessage(cause));
    }
  }, [principal]);

  useEffect(() => {
    const signal = { active: true };
    void load(signal);
    return () => { signal.active = false; };
  }, [load]);

  const allowedTypes = useMemo(() => [...new Set(catalog.flatMap(entry =>
    entry.definition.slots.map(slot => slot.component_type),
  ))].sort(), [catalog]);

  const locked = busy || pending !== null;
  const dirty = selected && draft
    ? JSON.stringify(draft) !== JSON.stringify(selected.definition)
    : Boolean(draft?.title || draft?.template_key);
  const mutability = readiness === "ready" && !locked && selected?.lifecycle !== "archived";

  const patch = (partial: Partial<CardDefinition>) => {
    if (!mutability) return;
    setDraft(current => current ? { ...current, ...partial } : current);
    setMessage("");
    setError("");
    setConflict(false);
  };
  const updateSlots = (slots: CardDefinition["slots"]) => patch({ slots });
  const moveSlot = (from: number, to: number) => {
    if (!mutability || !draft || from === to || from < 0 || to < 0 ||
        from >= draft.slots.length || to >= draft.slots.length) return;
    const slots = [...draft.slots];
    const [part] = slots.splice(from, 1);
    slots.splice(to, 0, part);
    updateSlots(slots);
  };
  const dropOn = (event: DragEvent<HTMLElement>, destination: number) => {
    event.preventDefault();
    const from = draft?.slots.findIndex(slot => slot.slot_id === draggedSlot) ?? -1;
    if (from >= 0) moveSlot(from, destination);
    setDraggedSlot(null);
  };

  const choose = (item: SavedCardTemplate | null) => {
    if (locked || !catalog.length) return;
    if (dirty && !window.confirm("Discard unsaved layout changes?")) return;
    setSelected(item);
    setDraft(item ? structuredClone(item.definition) : createBlankCardDraft(catalog));
    setError("");
    setConflict(false);
    setMessage(item ? `Loaded revision ${item.revision}. Changes are not saved.` : "New unsaved layout.");
  };

  const execute = async (request: CardMutation, replay = false) => {
    if (!principal || busy) return;
    if (!replay && pending) return;
    // A queued request must survive an uncertain network response, including
    // a tab reload. Do not transmit a mutation when recovery cannot be stored.
    if (!rememberPending(principal, request)) {
      setError("Unable to preserve retry identity in this browser tab. No save was attempted.");
      return;
    }
    setPending(request);
    setBusy(true);
    setError("");
    setMessage(replay ? "Replaying the exact original request…" : "Submitting draft…");
    try {
      const committed = await submitCardMutation(request);
      if (!rememberPending(principal, null)) {
        // The server confirmed a commit. Keep local recovery until deletion is
        // possible so a new page cannot silently reuse an uncertain key.
        setMessage(`Server confirmed revision ${committed.revision}; browser recovery could not be cleared.`);
      } else {
        setPending(null);
        setMessage(`Saved revision ${committed.revision} with a verified server receipt.`);
      }
      setSelected(committed);
      setDraft(structuredClone(committed.definition));
      setTemplates(current => insertOrReplace(current, committed));
      setConflict(false);
    } catch (cause) {
      const definiteDenial = cause instanceof ApiError &&
        [401, 403, 404, 409, 422].includes(cause.status);
      if (definiteDenial) {
        if (rememberPending(principal, null)) setPending(null);
        if (cause instanceof ApiError && cause.status === 409) setConflict(true);
      }
      setMessage("");
      setError(cardStudioErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft || !mutability || !principal) return;
    let safe: CardDefinition;
    try {
      safe = validateCardDefinition(draft, catalog);
    } catch (cause) {
      setError(cardStudioErrorMessage(cause));
      return;
    }
    if (selected && safe.template_key !== selected.template_key) {
      setError("A saved template key is immutable. Create a new layout to use a different key.");
      return;
    }
    const request: CardMutation = selected
      ? {
          operation: "revise",
          template_id: selected.template_id,
          expected_revision: selected.revision,
          idempotency_key: crypto.randomUUID(),
          draft: safe,
        }
      : { operation: "create", idempotency_key: crypto.randomUUID(), draft: safe };
    await execute(request);
  };

  const archive = async () => {
    if (!selected || !mutability || dirty || !principal) return;
    if (!window.confirm(`Archive ${selected.definition.title}? It will no longer be editable.`)) return;
    await execute({
      operation: "archive",
      idempotency_key: crypto.randomUUID(),
      template_id: selected.template_id,
      expected_revision: selected.revision,
    });
  };

  const refresh = async () => {
    if (locked || !catalog.length) return;
    if (dirty && !window.confirm("Discard unsaved edits and reload saved templates?")) return;
    setSelected(null);
    setDraft(null);
    await load();
  };

  if (!principal) {
    return <p role="status" className="p-6 text-sm">Verifying your Card Studio account scope…</p>;
  }
  if (readiness === "loading") {
    return <p role="status" className="p-6 text-sm">Checking Card Studio availability and your saved layouts…</p>;
  }
  if (readiness !== "ready") {
    return <section data-testid="card-studio-unavailable" className="mx-auto max-w-xl space-y-3 p-6">
      <h2 className="text-xl font-semibold">Card Studio unavailable</h2>
      <p className="text-sm text-muted-foreground">{error || "The backend has not enabled Card Studio for this session."}</p>
      <p className="text-xs text-muted-foreground">No local template is treated as saved, and no fallback renderer is activated.</p>
      <Button variant="outline" onClick={() => void load()}>Check again</Button>
    </section>;
  }

  return <div data-testid="card-studio-workspace" className="h-full min-h-0 overflow-y-auto p-3 md:p-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Card Studio</h2>
          <p className="text-sm text-muted-foreground">Arrange safe component slots. Only the runtime may attach verified content later.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={locked} onClick={() => void refresh()}>
            <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />Reload
          </Button>
          <Button type="button" variant="outline" disabled={locked} onClick={() => choose(null)}>
            <Plus aria-hidden="true" className="mr-2 h-4 w-4" />New layout
          </Button>
        </div>
      </header>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
        Draft only · Read-only components · No live data · No scripts or publication
      </p>

      {pending && <div role="alert" className="space-y-2 rounded-xl border border-amber-500/50 p-4 text-sm">
        <p className="font-semibold">Unverified save outcome</p>
        <p>This request has an unchanged retry key and payload. Editing and switching layouts are locked until it is resolved.</p>
        <Button type="button" variant="outline" disabled={busy}
          onClick={() => void execute(pending, true)}>
          Retry identical request
        </Button>
      </div>}
      {error && <p role="alert" className="rounded-lg border border-destructive/50 p-3 text-sm text-destructive">{error}</p>}
      {message && <p role="status" className="rounded-lg border border-border/70 p-3 text-sm">{message}</p>}
      {conflict && <p className="text-xs text-muted-foreground">Your local layout has not been saved. Use Reload to review the latest server revision.</p>}

      <div className="grid gap-4 xl:grid-cols-[minmax(220px,0.75fr)_minmax(320px,1.4fr)_minmax(300px,1.1fr)]">
        <aside aria-label="Saved card layouts" className="space-y-3 rounded-xl border border-border/70 p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Your layouts</h3>
            <span className="text-xs text-muted-foreground">{templates.length} returned</span>
          </div>
          {!templates.length && <p className="text-sm text-muted-foreground">No saved layouts were returned by your account.</p>}
          <ul className="space-y-2">{templates.map(item => <li key={item.template_id}>
            <button type="button" disabled={locked} aria-current={selected?.template_id === item.template_id ? "true" : undefined}
              onClick={() => choose(item)}
              className="w-full rounded-lg border border-border/70 p-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
              <span className="block truncate text-sm font-medium">{item.definition.title}</span>
              <span className="block text-xs text-muted-foreground">Revision {item.revision} · {item.lifecycle}</span>
            </button>
          </li>)}</ul>
        </aside>

        <section aria-label="Layout editor" className="space-y-4 rounded-xl border border-border/70 p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">Template definition</h3>
            {selected && <span className="text-xs text-muted-foreground">Server revision {selected.revision}</span>}
          </div>
          {draft && <>
            <div className="space-y-2">
              <Label htmlFor="card-studio-title">Title</Label>
              <Input id="card-studio-title" value={draft.title} maxLength={100}
                disabled={!mutability} onChange={event => patch({ title: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="card-studio-key">Template key</Label>
              <Input id="card-studio-key" value={draft.template_key} maxLength={64}
                placeholder="my-layout" disabled={!mutability || Boolean(selected)}
                onChange={event => patch({ template_key: event.target.value })} />
              <p className="text-xs text-muted-foreground">Lowercase letters, numbers and hyphens. Immutable after first save.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="card-studio-description">Description (optional)</Label>
              <Textarea id="card-studio-description" rows={2} maxLength={240} disabled={!mutability}
                value={draft.description ?? ""} onChange={event =>
                  patch({ description: event.target.value ? event.target.value : undefined })
                } />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="card-studio-layout">Layout</Label>
                <select id="card-studio-layout" disabled={!mutability} value={draft.layout}
                  onChange={event => patch({ layout: event.target.value as CardDefinition["layout"] })}
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm">
                  <option value="stack">Stack</option><option value="grid">Grid</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="card-studio-density">Density</Label>
                <select id="card-studio-density" disabled={!mutability} value={draft.density}
                  onChange={event => patch({ density: event.target.value as CardDefinition["density"] })}
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm">
                  <option value="comfortable">Comfortable</option><option value="compact">Compact</option>
                </select>
              </div>
            </div>
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold">Slots ({draft.slots.length}/6)</h4>
              <Button type="button" size="sm" variant="outline"
                disabled={!mutability || draft.slots.length >= 6}
                onClick={() => updateSlots([...draft.slots, {
                  slot_id: nextSlotId(draft.slots), component_type: allowedTypes[0],
                }])}><Plus className="mr-1 h-4 w-4" aria-hidden="true" />Add slot</Button>
            </div>
            <ul className="space-y-2" aria-label="Reorder card slots">{draft.slots.map((slot, index) => (
              <li key={slot.slot_id} draggable={mutability}
                onDragStart={() => setDraggedSlot(slot.slot_id)}
                onDragOver={event => { if (mutability) event.preventDefault(); }}
                onDrop={event => dropOn(event, index)}
                onDragEnd={() => setDraggedSlot(null)}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 p-2">
                <GripVertical aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                <span className="min-w-[60px] text-xs font-medium">{slot.slot_id}</span>
                <select aria-label={`Component for ${slot.slot_id}`} disabled={!mutability}
                  value={slot.component_type}
                  onChange={event => updateSlots(draft.slots.map(entry =>
                    entry.slot_id === slot.slot_id
                      ? { ...entry, component_type: event.target.value } : entry))}
                  className="h-9 min-w-[140px] flex-1 rounded-md border bg-background px-2 text-xs">
                  {allowedTypes.map(type => <option key={type} value={type}>{labelForComponent(type)}</option>)}
                </select>
                <div className="flex items-center gap-1">
                  <Button type="button" size="icon" variant="outline" className="h-9 w-9" disabled={!mutability || index === 0}
                    aria-label={`Move ${slot.slot_id} up`} onClick={() => moveSlot(index, index - 1)}>
                    <ArrowUp className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button type="button" size="icon" variant="outline" className="h-9 w-9"
                    disabled={!mutability || index === draft.slots.length - 1}
                    aria-label={`Move ${slot.slot_id} down`} onClick={() => moveSlot(index, index + 1)}>
                    <ArrowDown className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button type="button" size="icon" variant="outline" className="h-9 w-9"
                    disabled={!mutability || draft.slots.length === 1}
                    aria-label={`Remove ${slot.slot_id}`}
                    onClick={() => updateSlots(draft.slots.filter(item => item.slot_id !== slot.slot_id))}>
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}</ul>
            <div className="flex flex-wrap gap-2">
              <Button type="button" disabled={!mutability || (Boolean(selected) && !dirty)} onClick={() => void save()}>
                <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                {selected ? "Save revision" : "Create draft"}
              </Button>
              {selected && selected.lifecycle === "draft" && <Button type="button" variant="outline"
                disabled={!mutability || Boolean(dirty)} onClick={() => void archive()}>
                <Archive className="mr-2 h-4 w-4" aria-hidden="true" />Archive
              </Button>}
            </div>
          </>}
        </section>

        <section aria-label="Inert layout preview" className="space-y-3 rounded-xl border border-border/70 p-4">
          <div>
            <h3 className="font-semibold">Layout preview</h3>
            <p className="text-xs text-muted-foreground">Geometry only. No fabricated measurements, source evidence or runnable code.</p>
          </div>
          {draft && <div data-testid="card-studio-preview" aria-label="Unbound card layout"
            className={draft.layout === "grid" ? "grid grid-cols-1 gap-3 sm:grid-cols-2" : "flex flex-col gap-3"}>
            {draft.slots.map(slot => <article key={slot.slot_id}
              className={`min-w-0 rounded-xl border border-dashed border-border bg-muted/15 ${draft.density === "compact" ? "p-3" : "p-5"}`}>
              <div className="text-sm font-semibold">{labelForComponent(slot.component_type)}</div>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">{slot.slot_id}</p>
              <p className="mt-4 border-t border-dashed pt-3 text-xs text-muted-foreground">Not connected to runtime evidence</p>
            </article>)}
          </div>}
        </section>
      </div>
    </div>
  </div>;
}
