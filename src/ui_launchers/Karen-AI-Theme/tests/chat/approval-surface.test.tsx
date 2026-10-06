import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MessageBubble } from '@/components/chat/MessageBubble';
import type { ChatMessage } from '@/lib/types';

describe('durable approval surface', () => {
  it('renders approval actions as a governed decision, not a generic suggestion', () => {
    const onActionClick = vi.fn();
    const message: ChatMessage = {
      id: 'approval-1',
      role: 'assistant',
      content: 'Approval required before KAREN can continue this action.',
      timestamp: new Date('2026-10-06T12:00:00Z'),
      status: 'completed',
      metadata: {
        mode: 'approval_required',
        approval_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        approval_status: 'pending',
      },
      actions: [
        {
          type: 'approval.approve',
          description: 'Approve',
          params: {
            approval_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          },
        },
        {
          type: 'approval.reject',
          description: 'Reject',
          params: {
            approval_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          },
        },
      ],
    };

    render(<MessageBubble message={message} onActionClick={onActionClick} />);

    expect(screen.getByText('Approval required')).toBeTruthy();
    expect(screen.queryByText('Suggested Actions')).toBeNull();
    expect(JSON.stringify(message.actions)).not.toContain('original_input');

    fireEvent.click(screen.getByRole('button', { name: /perform action: approve/i }));
    expect(onActionClick).toHaveBeenCalledWith(message.actions?.[0]);

    fireEvent.click(screen.getByRole('button', { name: /perform action: reject/i }));
    expect(onActionClick).toHaveBeenCalledWith(message.actions?.[1]);
  });
});
