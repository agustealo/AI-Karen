export type SearchModeId =
  | 'general'
  | 'news'
  | 'docs'
  | 'deep_research'
  | 'structured_extract'
  | 'weather'
  | 'stock_market';

export interface SearchSourceItem {
  id: string;
  url: string;
  title: string;
  snippet?: string;
  content?: string;
  full_content?: string;
  markdown?: string;
  extracted_data?: Record<string, unknown>;
  publishedDate?: string;
  relevanceScore?: number;
  domain?: string;
  links?: Array<{ url: string; text: string; category?: string }>;
  media?: Record<string, unknown>;
}

export interface SearchResultItem {
  id: string;
  title: string;
  url: string;
  domain?: string;
  snippet?: string;
  content?: string;
  score?: number;
  markdown?: string;
  extracted_data?: Record<string, unknown>;
}

export interface SearchDiagnostics {
  mode: SearchModeId;
  strategy?: string;
  latencyMs?: number;
  sourceCount?: number;
  urlsFound?: number;
  pagesCrawled?: number;
  chunksProduced?: number;
  warnings?: string[];
  degraded?: boolean;
}

export interface WeatherCondition {
  temp: number;
  condition: string;
  humidity?: number;
  windSpeed?: number;
  windDirection?: string;
  feelsLike?: number;
  pressure?: number;
  uvIndex?: number;
  visibility?: number;
  precipProbability?: number;
  icon?: string;
}

export interface WeatherForecast {
  date: string;
  high: number;
  low: number;
  condition: string;
  precipProbability?: number;
  icon?: string;
}

export interface WeatherAlert {
  event: string;
  severity: string;
  description: string;
  start: string;
  end: string;
}

export interface WeatherResult {
  location: string;
  current?: WeatherCondition;
  daily?: WeatherForecast[];
  hourly?: WeatherCondition[];
  alerts?: WeatherAlert[];
  units: 'metric' | 'imperial';
}

export interface IntelligentSearchResponse {
  summary: string;
  query?: string;
  mode?: SearchModeId | string;
  provider?: string;
  total_results?: number;
  search_time?: number;
  can_execute?: boolean;
  reason?: string;
  sources?: SearchSourceItem[];
  extractedData?: Record<string, unknown>;
  insights?: string[];
  diagnostics?: SearchDiagnostics;
  results?: SearchResultItem[];
  liveSearch?: {
    mode?: string;
    query?: string;
    expanded_queries?: string[];
    urls?: string[];
    crawl_results?: Array<Record<string, unknown>>;
    processed_chunks?: Array<Record<string, unknown>>;
  };
  metadata?: Record<string, unknown>;
  execution_time_ms?: number;
  weather?: WeatherResult;
}

export interface PluginExecutionEnvelope<T> {
  success?: boolean;
  result?: T;
  data?: T;
  payload?: T;
  error?: string;
  message?: string;
}

export interface IntelligentSearchOptions {
  maxUrls?: number;
  freshnessBias?: string;
  allowedDomains?: string[];
  blockedDomains?: string[];
  timeRange?: string;
  preferRecent?: boolean;
  product?: string;
  version?: string;
  officialOnly?: boolean;
  docTypes?: string[];
  maxSubqueries?: number;
  maxHops?: number;
  sourceDiversity?: number;
  schema?: string;
  instruction?: string;
  targetFields?: string[];
  targetSelectors?: string[];
  location?: string;
  units?: string;
  includeCurrent?: boolean;
  includeHourly?: boolean;
  includeDaily?: boolean;
  includeAlerts?: boolean;
  ticker?: string;
  companyName?: string;
  exchange?: string;
  includePriceAction?: boolean;
  includeCompanyNews?: boolean;
  includeEarnings?: boolean;

  // Crawl4AI-specific options
  crawlEnabled?: boolean;
  crawlMaxPages?: number;
  crawlMaxDepth?: number;
  crawlCaptureScreenshot?: boolean;
  crawlUseCache?: boolean;
  crawlRespectRobotsTxt?: boolean;
  crawlIncludeDomains?: string[];
  crawlExcludeDomains?: string[];
  crawlExtractLinks?: boolean;
  crawlExtractMedia?: boolean;
  crawlExtractCleanedHtml?: boolean;
  crawlStructuredSchema?: string;
  crawlWaitForSelector?: string;
}

export interface IntelligentSearchState {
  query: string;
  mode: SearchModeId;
  options: IntelligentSearchOptions;
  isLoading: boolean;
  error: Error | null;
  response: IntelligentSearchResponse | null;
}

// Aliases for backward compatibility if needed, but primary naming is now IntelligentSearch
export type WebSearchResponse = IntelligentSearchResponse;
export type WebSearchOptions = IntelligentSearchOptions;
export type WebSearchState = IntelligentSearchState;
