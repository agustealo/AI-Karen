import React from 'react';
import { useIntelligentSearch } from './hooks/useIntelligentSearch';
import { SearchHeader } from './components/SearchHeader';
import { SearchQueryInput } from './components/SearchQueryInput';
import { ModeSelector } from './components/ModeSelector';
import { ModeSpecificControls } from './components/ModeSpecificControls';
import { ResultsWorkspace } from './components/ResultsWorkspace';
import { SearchControlsPanel } from './components/SearchControlsPanel';

/**
 * IntelligentSearchPage Component
 * 
 * The main entry point for the Intelligent Search plugin.
 * Features a modern, responsive design with live crawl capabilities,
 * multiple search modes, and a robust results workspace.
 */
export default function IntelligentSearchPage() {
  const {
    state,
    modeConfig,
    setQuery,
    setMode,
    updateOptions,
    executeSearch,
    resetSearch,
  } = useIntelligentSearch();

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Header Section */}
      <div className="p-4 lg:p-6 pb-0">
        <SearchHeader modeConfig={modeConfig} state={state} />
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden p-4 lg:p-6 gap-6">
        
        {/* Left Column: Search Controls */}
        <aside className="w-full lg:w-[400px] flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar">
          <SearchControlsPanel 
            state={state}
            modeConfig={modeConfig}
            onQueryChange={setQuery}
            onModeChange={setMode}
            onOptionsChange={updateOptions}
            onSubmit={executeSearch}
          />

          {/* Optional Reset Button */}
          <div className="px-4 md:px-0">
            <button
              onClick={resetSearch}
              className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              Clear search results
            </button>
          </div>
        </aside>

        {/* Right Column: Results Workspace */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
          <ResultsWorkspace 
            state={state} 
            modeConfig={modeConfig} 
          />
        </main>
      </div>
    </div>
  );
}
