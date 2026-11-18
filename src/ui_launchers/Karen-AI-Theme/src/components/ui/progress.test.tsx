import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Progress } from './progress';

describe('Progress accessibility', () => {
  it('exposes the actual supplied percentage to assistive technology', () => {
    render(<Progress value={62} aria-label="Recorded outcome progress" />);
    const meter = screen.getByRole('progressbar', { name: 'Recorded outcome progress' });

    expect(meter.getAttribute('aria-valuenow')).toBe('62');
    expect(meter.getAttribute('aria-valuemax')).toBe('100');
    expect(meter.getAttribute('aria-valuemin')).toBe('0');
  });

  it('does not announce an invented score when the value is unavailable', () => {
    render(<Progress aria-label="Unavailable progress" />);
    const meter = screen.getByRole('progressbar', { name: 'Unavailable progress' });

    expect(meter.getAttribute('aria-valuenow')).toBeNull();
  });
});
