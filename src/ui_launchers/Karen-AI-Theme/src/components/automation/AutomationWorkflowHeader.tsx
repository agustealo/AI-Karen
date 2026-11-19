import type { LucideIcon } from "lucide-react";

interface AutomationWorkflowHeaderProps {
  icon: LucideIcon;
  section: string;
  title: string;
  description: string;
}

/**
 * Presentation-only Automation workspace header.
 *
 * Content is supplied by the owning page; this component does not fetch
 * operational state, choose runtime behavior, or imply workflow readiness.
 */
export function AutomationWorkflowHeader({
  icon: Icon,
  section,
  title,
  description,
}: AutomationWorkflowHeaderProps) {
  return (
    <header className="karen-automation-hero karen-surface relative overflow-hidden rounded-2xl px-5 py-6 sm:px-8 sm:py-8">
      <div className="relative z-10 flex min-w-0 items-start gap-4">
        <div className="rounded-xl border border-primary/20 bg-primary/10 p-3 text-primary">
          <Icon className="h-6 w-6" aria-hidden="true" />
        </div>
        <div className="min-w-0 space-y-2">
          <p className="karen-panel-label">KARI OS / AUTOMATIONS / {section}</p>
          <h2 className="karen-page-title">{title}</h2>
          <p className="karen-page-description">{description}</p>
        </div>
      </div>
    </header>
  );
}
