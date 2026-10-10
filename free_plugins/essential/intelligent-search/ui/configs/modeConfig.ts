import { SearchModeId } from '../types';

export interface ModeConfigItem {
  label: string;
  description: string;
  visibleControls: string[];
  resultTabs: string[];
}

export const MODE_CONFIG: Record<SearchModeId, ModeConfigItem> = {
  general: {
    label: "General",
    description: "Broad web search",
    visibleControls: ["maxUrls", "freshnessBias", "allowedDomains", "blockedDomains"],
    resultTabs: ["results", "sources", "extractedData", "diagnostics"],
  },
  news: {
    label: "News",
    description: "Recent reporting and updates",
    visibleControls: ["timeRange", "preferRecent", "allowedDomains", "blockedDomains"],
    resultTabs: ["results", "sources", "extractedData", "diagnostics"],
  },
  docs: {
    label: "Docs",
    description: "Technical docs and API guides",
    visibleControls: ["product", "version", "officialOnly", "docTypes"],
    resultTabs: ["results", "sources", "extractedData", "diagnostics"],
  },
  deep_research: {
    label: "Deep Research",
    description: "Multi-source synthesis and comparison",
    visibleControls: ["maxSubqueries", "maxHops", "sourceDiversity"],
    resultTabs: ["results", "sources", "extractedData", "insights", "diagnostics"],
  },
  structured_extract: {
    label: "Structured Extract",
    description: "Extract fields and structured results",
    visibleControls: ["schema", "instruction", "targetFields", "targetSelectors"],
    resultTabs: ["results", "sources", "extractedData", "diagnostics"],
  },
  weather: {
    label: "Weather",
    description: "Current conditions and forecast",
    visibleControls: ["location", "units", "includeCurrent", "includeHourly", "includeDaily", "includeAlerts"],
    resultTabs: ["results", "extractedData", "diagnostics"],
  },
  stock_market: {
    label: "Stock Market",
    description: "Market context and company signals",
    visibleControls: ["ticker", "companyName", "exchange", "includePriceAction", "includeCompanyNews", "includeEarnings"],
    resultTabs: ["results", "sources", "extractedData", "diagnostics"],
  },
};
