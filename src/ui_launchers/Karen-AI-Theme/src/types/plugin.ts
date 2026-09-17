import { z } from 'zod';

export const PluginCategorySchema = z.string().min(1);
export type PluginCategory = z.infer<typeof PluginCategorySchema>;

export const PluginSortOrderSchema = z.enum([
  'popularity',
  'newest',
  'name',
  'updated',
  'rating',
]);

export type PluginSortOrder = z.infer<typeof PluginSortOrderSchema>;

export const PluginStatusSchema = z.enum([
  'installed',
  'available',
  'compatible',
  'incompatible',
]);

export type PluginStatus = z.infer<typeof PluginStatusSchema>;

export const PluginSchema = z.object({
  id: z.string(),
  name: z.string(),
  display_name: z.string(),
  description: z.string(),
  author: z.string(),
  version: z.string(),
  status: PluginStatusSchema,
  runtime_status: z.string().optional(),
  category: PluginCategorySchema.optional(),
  downloads: z.number().nullable().optional(),
  rating: z.number().nullable().optional(),
  rating_count: z.number().nullable().optional(),
  latest_version: z.string().nullable().optional(),
  installed_at: z.string().nullable().optional(),
  icon: z.string().optional(),
  marketplace_url: z.string().optional(),
  homepage_url: z.string().optional(),
  repository_url: z.string().optional(),
  documentation_url: z.string().nullable().optional(),
  support_url: z.string().nullable().optional(),
  license: z.string().nullable().optional(),
  tags: z.array(z.string()).optional(),
  compatibility: z.object({
    min_karen_version: z.string().nullable().optional(),
    max_karen_version: z.string().nullable().optional(),
    requirements: z.array(z.string()).optional(),
  }).optional(),
  dependencies: z.array(z.string()).optional(),
});

export type Plugin = z.infer<typeof PluginSchema>;

export const PluginSearchParamsSchema = z.object({
  query: z.string().optional(),
  category: PluginCategorySchema.optional(),
  sort_by: PluginSortOrderSchema.default('popularity'),
  page: z.number().min(1).default(1),
  per_page: z.number().min(1).max(100).default(20),
  min_version: z.string().optional(),
  max_version: z.string().optional(),
});

export type PluginSearchParams = z.infer<typeof PluginSearchParamsSchema>;

export const PluginSearchResponseSchema = z.object({
  plugins: z.array(PluginSchema),
  total: z.number(),
  page: z.number(),
  per_page: z.number(),
  total_pages: z.number(),
  has_next: z.boolean(),
});

export type PluginSearchResponse = z.infer<typeof PluginSearchResponseSchema>;

export const PluginDetailsSchema = z.object({
  plugin: PluginSchema.optional(),
  marketplace_info: z.any().optional(),
  analytics: z.any().optional(),
  installed: z.boolean(),
  update_available: z.boolean().nullable().optional(),
});

export type PluginDetails = z.infer<typeof PluginDetailsSchema>;

export const PluginInstallRequestSchema = z.object({
  plugin_id: z.string(),
  version: z.string().optional(),
});

export type PluginInstallRequest = z.infer<typeof PluginInstallRequestSchema>;

export const PluginInstallResponseSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  plugin_id: z.string().optional(),
  version: z.string().optional(),
  operation: z.string().optional(),
  error: z.string().optional(),
});

export type PluginInstallResponse = z.infer<typeof PluginInstallResponseSchema>;

export const PluginRatingRequestSchema = z.object({
  plugin_id: z.string(),
  rating: z.number().min(1).max(5),
  review: z.string().min(10).max(1000),
});

export type PluginRatingRequest = z.infer<typeof PluginRatingRequestSchema>;

export const PluginRatingResponseSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

export type PluginRatingResponse = z.infer<typeof PluginRatingResponseSchema>;

export const PluginStoreStatsSchema = z.object({
  total_plugins: z.number(),
  active_plugins: z.number(),
  total_downloads: z.number().nullable().optional(),
  total_ratings: z.number().nullable().optional(),
  recent_updates: z.number().nullable().optional(),
});

export type PluginStoreStats = z.infer<typeof PluginStoreStatsSchema>;

export const CategoryInfoSchema = z.object({
  name: z.string(),
  display_name: z.string(),
  plugin_count: z.number(),
});

export type CategoryInfo = z.infer<typeof CategoryInfoSchema>;

export const PluginUpdateSchema = z.object({
  plugin_id: z.string(),
  current_version: z.string(),
  latest_version: z.string().nullable().optional(),
  update_available: z.boolean(),
});

export type PluginUpdate = z.infer<typeof PluginUpdateSchema>;
