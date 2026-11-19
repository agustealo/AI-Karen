import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface AutomationMetricCardProps {
  title: string;
  icon: LucideIcon;
  metricId: "active-tasks" | "tasks-today" | "defined-sequences" | "next-job";
  value: ReactNode;
  description: ReactNode;
  descriptionMetricId?: "tasks-today-context" | "next-job-time";
  compactValue?: boolean;
}

/**
 * Presentation-only metric card. The overview retains sole authority for
 * authenticated data acquisition, validation, and unavailable-state rendering.
 */
export function AutomationMetricCard({
  title,
  icon: Icon,
  metricId,
  value,
  description,
  descriptionMetricId,
  compactValue = false,
}: AutomationMetricCardProps) {
  return (
    <Card className="karen-automation-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <div
          className={`font-instrument break-words ${compactValue ? "text-lg" : "text-2xl"} font-bold tracking-tight`}
          data-automation-metric={metricId}
        >
          {value}
        </div>
        <p className="text-xs text-muted-foreground" data-automation-metric={descriptionMetricId}>
          {description}
        </p>
      </CardContent>
    </Card>
  );
}
