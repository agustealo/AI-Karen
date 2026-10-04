export interface SuggestedAction {
  type: string;
  params?: Record<string, string | number | boolean | null | undefined>;
  confidence?: number;
  description?: string;
}

