'use client';

import { Children, isValidElement, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Settings2, GripVertical } from 'lucide-react';
import { CardTitle } from '@/components/ui/card';

const STORAGE_KEY = 'karen.intelligence.cards.v1';
type CardPreference = { order: string[]; hidden: string[] };

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  if (!isValidElement<{ children?: ReactNode }>(node)) return '';
  if (node.type === CardTitle) return textOf(node.props.children).trim();
  return Children.toArray(node.props.children).map(textOf).join(' ').trim();
}

function restore(): CardPreference {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
    return {
      order: Array.isArray(value.order) ? value.order.filter((id: unknown) => typeof id === 'string') : [],
      hidden: Array.isArray(value.hidden) ? value.hidden.filter((id: unknown) => typeof id === 'string') : [],
    };
  } catch {
    return { order: [], hidden: [] };
  }
}

/** Presentation preferences only. Cards and their evidence remain backend-owned. */
export default function CustomizableCardDeck({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<CardPreference>({ order: [], hidden: [] });
  const [editing, setEditing] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  useEffect(() => setPreferences(restore()), []);
  const cards = Children.toArray(children).map((element, index) => {
    const title = textOf(element) || `Card ${index + 1}`;
    return { id: title.toLowerCase().replace(/[^a-z0-9]+/g, '-'), title, element };
  });
  const ordered = [...cards].sort((a, b) => {
    const index = (id: string) => {
      const position = preferences.order.indexOf(id);
      return position < 0 ? preferences.order.length + cards.findIndex((card) => card.id === id) : position;
    };
    return index(a.id) - index(b.id);
  });
  const persist = (next: CardPreference) => {
    setPreferences(next);
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); }
    catch { /* Session-only customizations remain usable when storage is blocked. */ }
  };
  const move = (source: string, destination: string) => {
    if (source === destination) return;
    const ids = ordered.map((card) => card.id);
    const from = ids.indexOf(source);
    const to = ids.indexOf(destination);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, source);
    persist({ ...preferences, order: ids });
  };
  const shift = (id: string, direction: number) => {
    const ids = ordered.map((card) => card.id);
    const index = ids.indexOf(id);
    const next = index + direction;
    if (next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    persist({ ...preferences, order: ids });
  };
  return <div className="space-y-3">
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold tracking-tight">Cards</h3>
      <button type="button" aria-label="Customize intelligence cards" aria-expanded={editing}
        onClick={() => setEditing(!editing)} className="rounded-lg border p-2 hover:bg-muted">
        <Settings2 className="h-4 w-4" />
      </button>
    </div>
    {editing && <p className="text-xs text-muted-foreground">Show, hide, drag, or use arrows to arrange cards. Saved in this browser.</p>}
    {ordered.map(({ id, title, element }, index) => <div key={id}
      draggable={editing} onDragStart={() => setDragging(id)}
      onDragOver={(event) => { if (editing) event.preventDefault(); }}
      onDrop={(event) => { event.preventDefault(); if (dragging) move(dragging, id); setDragging(null); }}
      onDragEnd={() => setDragging(null)}>
      {editing && <div className="mb-1 flex items-center gap-2 rounded-lg border px-2 py-1 text-xs">
        <GripVertical className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <input type="checkbox" checked={!preferences.hidden.includes(id)}
            onChange={(event) => persist({ ...preferences, hidden: event.target.checked
              ? preferences.hidden.filter((item) => item !== id)
              : [...preferences.hidden, id] })} />
          <span className="truncate">{title}</span>
        </label>
        <button type="button" disabled={index === 0} onClick={() => shift(id, -1)}
          aria-label={`Move ${title} up`} className="rounded border px-2 py-1 disabled:opacity-30">↑</button>
        <button type="button" disabled={index === ordered.length - 1} onClick={() => shift(id, 1)}
          aria-label={`Move ${title} down`} className="rounded border px-2 py-1 disabled:opacity-30">↓</button>
      </div>}
      {!preferences.hidden.includes(id) && element}
    </div>)}
  </div>;
}
