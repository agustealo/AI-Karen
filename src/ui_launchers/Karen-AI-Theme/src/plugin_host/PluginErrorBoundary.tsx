/**
 * Plugin_Error_Boundary — isolates plugin render failures.
 *
 * Catches errors from plugin UI components and displays a fallback UI
 * without crashing the host application. Provides reload functionality.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4
 */

import React from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PluginErrorBoundaryProps {
  pluginId: string;
  children: React.ReactNode;
  onRenderError?: () => void;
  onReload?: () => void;
}

export interface PluginErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

// ─── Plugin_Error_Boundary ─────────────────────────────────────────────────────

export class PluginErrorBoundary extends React.Component<
  PluginErrorBoundaryProps,
  PluginErrorBoundaryState
> {
  constructor(props: PluginErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): PluginErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.props.onRenderError?.();
    console.error(
      `[PluginErrorBoundary] Plugin "${this.props.pluginId}" crashed:`,
      error,
      info
    );
  }

  handleReload = () => {
    this.props.onReload?.();
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 border border-dashed rounded text-center text-sm text-muted-foreground bg-muted/10 flex flex-col items-center gap-2">
          <svg
            className="h-5 w-5 text-destructive"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p>
            The <span className="font-mono">{this.props.pluginId}</span> UI crashed during render.
          </p>
          <button
            className="mt-1 text-xs underline hover:text-foreground transition-colors"
            onClick={this.handleReload}
          >
            Reload
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}