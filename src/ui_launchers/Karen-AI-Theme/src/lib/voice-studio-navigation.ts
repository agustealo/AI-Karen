/**
 * Canonical host navigation contract for TTS-capable plugin entry points.
 *
 * This is navigation only. No plugin can declare model readiness, grant access,
 * or choose a synthesis provider through query parameters.
 */
export const VOICE_STUDIO_DASHBOARD_HREF =
  '/dashboard?view=settings&section=voice' as const;

/** Accept only the documented Voice Studio landing target. */
export function isVoiceStudioDashboardRoute(search: string): boolean {
  const query = new URLSearchParams(search);
  return query.getAll('view').length === 1 &&
    query.getAll('section').length === 1 &&
    query.get('view') === 'settings' &&
    query.get('section') === 'voice';
}

/** User-facing plugin workspace. This is not an authorization decision. */
export const POCKET_TTS_DASHBOARD_HREF = '/dashboard?view=pocket-tts' as const;

export function isPocketTtsDashboardRoute(search: string): boolean {
  const query = new URLSearchParams(search);
  return query.getAll('view').length === 1 &&
    query.get('view') === 'pocket-tts' &&
    query.getAll('section').length === 0;
}
