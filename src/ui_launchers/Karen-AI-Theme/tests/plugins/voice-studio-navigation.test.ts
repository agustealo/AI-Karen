import { describe, expect, it } from 'vitest';
import {
  VOICE_STUDIO_DASHBOARD_HREF,
  isVoiceStudioDashboardRoute,
} from '@/lib/voice-studio-navigation';

describe('host-owned Voice Studio deep-link contract', () => {
  it('opens the existing Dashboard settings destination', () => {
    const destination = new URL(VOICE_STUDIO_DASHBOARD_HREF, 'https://karen.local');
    expect(destination.pathname).toBe('/dashboard');
    expect(isVoiceStudioDashboardRoute(destination.search)).toBe(true);
  });

  it.each([
    '',
    '?view=settings',
    '?section=voice',
    '?view=plugins&section=voice',
    '?view=settings&section=models',
    '?view=settings&section=voice2',
    '?view=settings&section=voice&section=behavior',
    '?view=chat&view=settings&section=voice',
  ])('does not change the Dashboard view for unrelated or ambiguous query %s', (search) => {
    expect(isVoiceStudioDashboardRoute(search)).toBe(false);
  });
});
