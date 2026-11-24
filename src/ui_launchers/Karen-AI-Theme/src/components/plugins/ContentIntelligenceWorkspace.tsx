'use client';

import { SharedFileExplorer } from '@/plugin_repo/file-explorer/FileExplorerPage';
import { FileExplorerInventoryHost } from './FileExplorerInventoryHost';

/**
 * Standalone document investigation view. The shared picker is a controlled
 * presentation component, not a File Explorer lifecycle grant. The inventory
 * host requests Content Intelligence's independently authorized endpoint.
 */
export function ContentIntelligenceWorkspace() {
  return (
    <main aria-label="Content Intelligence workspace" className="min-w-0 space-y-5 p-4 sm:p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Content Intelligence</h1>
        <p className="text-sm text-muted-foreground">
          Investigate authorized documents using analysis, lexical search and comparison.
          Source permissions and revisions are checked again before execution.
        </p>
      </header>
      <div className="grid min-w-0 gap-4 xl:grid-cols-2 xl:items-start">
        <FileExplorerInventoryHost consumer="content-intelligence" mode="analysis"
          renderAnalysis={(panel, props) => (
            <section aria-label="Document investigation" className="min-w-0 space-y-3 rounded-lg border p-4">
              <h2 className="text-lg font-semibold">Investigation</h2>
              {panel ?? (
                <p role="status" className="text-sm text-muted-foreground">
                  {props.loading ? 'Checking authorized sources…'
                    : props.error || !props.authorized ? 'Document investigation is unavailable until inventory access is verified.'
                    : 'Select supported text or code files to analyze, search or compare.'}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Selection is not a content access grant. Results are lexical evidence, not semantic conclusions.
              </p>
            </section>
          )}>
          {(props) => <div className="min-w-0"><SharedFileExplorer {...props} multiSelect /></div>}
        </FileExplorerInventoryHost>
      </div>
    </main>
  );
}
