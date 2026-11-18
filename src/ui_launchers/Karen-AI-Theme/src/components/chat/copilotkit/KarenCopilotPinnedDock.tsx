"use client";

/**
 * KUI-002C stationary dock surface.
 *
 * This is deliberately an unavailable state, NOT a client-side pin store.
 * Authoritative pin listing, mutation, ownership, revision and revalidation
 * must be implemented by Karen's canonical artifact/runtime boundary before
 * enabling user pin actions or displaying cross-conversation material here.
 */
import { Bookmark, ShieldCheck } from "lucide-react";

export function KarenCopilotPinnedDock() {
  return (
    <aside
      aria-label="Pinned workspace"
      data-testid="karen-copilot-pinned-dock"
      data-kari-region="dock"
      className="karen-pinned-dock"
    >
      <header className="karen-pinned-dock-header">
        <div className="flex min-w-0 items-center gap-2">
          <Bookmark aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
          <h2 className="truncate font-semibold">Pinned workspace</h2>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Stationary cards, subject to your permissions
        </p>
      </header>
      <div className="karen-pinned-dock-scroll">
        <section
          aria-label="Pinning availability"
          data-testid="karen-pinning-not-available"
          className="rounded-xl border border-border/70 bg-card p-4"
        >
          <ShieldCheck aria-hidden="true" className="mb-3 h-5 w-5 text-primary" />
          <h3 className="text-sm font-semibold">Secure pinning not yet available</h3>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            Karen is not yet connected to a verified, account-scoped pin
            service. Generated cards remain in their original saved responses.
            Nothing has been pinned or synced from this panel.
          </p>
        </section>
      </div>
    </aside>
  );
}
