import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusIndicators } from '@/components/chat/interface/StatusIndicators';
import type { Session } from '@/components/chat/types';

const session: Session = {
  id: 'session-1',
  title: 'Recovered conversation',
  createdAt: new Date('2026-10-02T10:00:00Z'),
  updatedAt: new Date('2026-10-02T10:00:00Z'),
  messageCount: 2,
  isActive: true,
};

describe('StatusIndicators recovery truth', () => {
  it('keeps locally restored messages visibly provisional until server confirmation', () => {
    render(
      <StatusIndicators
        isBackendOffline={false}
        error={null}
        currentSession={session}
        isLoading={false}
        isLocalRecoveryUnconfirmed
      />,
    );

    expect(screen.getByTestId('local-recovery-unconfirmed')).toBeTruthy();
    expect(screen.getByText('Local recovery only')).toBeTruthy();
    expect(
      screen.getByText(/server has not confirmed them in durable conversation history yet/i),
    ).toBeTruthy();
  });

  it('hides the provisional warning after server history is confirmed', () => {
    render(
      <StatusIndicators
        isBackendOffline={false}
        error={null}
        currentSession={session}
        isLoading={false}
        isLocalRecoveryUnconfirmed={false}
      />,
    );

    expect(screen.queryByTestId('local-recovery-unconfirmed')).toBeNull();
  });
});
