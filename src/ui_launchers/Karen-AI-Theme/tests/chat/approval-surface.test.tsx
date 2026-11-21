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

  it('renders an approved unconsumed receipt as Resume instead of another decision', () => {
    const onActionClick = vi.fn();
    const message: ChatMessage = {
      id: 'approval-2',
      role: 'assistant',
      content: 'Approval granted. KAREN is ready to resume this action.',
      timestamp: new Date('2026-10-06T12:05:00Z'),
      status: 'completed',
      metadata: {
        mode: 'approval_required',
        approval_projection: true,
        approval_id: 'ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee',
        approval_status: 'approved',
      },
      actions: [
        {
          type: 'approval.resume',
          description: 'Resume',
          params: {
            approval_id: 'ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee',
          },
        },
      ],
    };

    render(<MessageBubble message={message} onActionClick={onActionClick} />);

    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /reject/i })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /perform action: resume/i }));
    expect(onActionClick).toHaveBeenCalledWith(message.actions?.[0]);
  });

  it('routes source-specific document consent to separate authenticated review, never chat approval', () => {
    const onActionClick = vi.fn();
    const approvalId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
    const message: ChatMessage = {
      id: 'document-consent-review',
      role: 'assistant',
      content: 'The document author must review and approve this exact source.',
      timestamp: new Date('2026-11-21T18:00:00Z'),
      status: 'completed',
      metadata: {
        mode: 'approval_required',
        intent: 'writing_style.document_consent.issue',
        approval_id: approvalId,
        approval_status: 'pending',
      },
      actions: [
        { type: 'approval.approve', description: 'Approve', params: { approval_id: approvalId } },
        { type: 'approval.reject', description: 'Reject', params: { approval_id: approvalId } },
      ],
    };

    render(<MessageBubble message={message} onActionClick={onActionClick} />);
    const link = screen.getByRole('link', { name: 'Review document author consent' });
    expect(link.getAttribute('href')).toBe(
      '/approvals/document-consent/' + approvalId,
    );
    expect(screen.queryByRole('button', { name: /perform action: approve/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /perform action: reject/i })).toBeNull();
    expect(onActionClick).not.toHaveBeenCalled();
  });

  it('does not invent an author-consent action from an invalid approval reference', () => {
    const message: ChatMessage = {
      id: 'document-consent-invalid',
      role: 'assistant',
      content: 'Author review required.',
      timestamp: new Date('2026-11-21T18:05:00Z'),
      status: 'completed',
      metadata: {
        mode: 'approval_required',
        intent: 'writing_style.document_consent.issue',
        approval_id: 'invalid',
        approval_status: 'pending',
      },
      actions: [
        { type: 'approval.approve', description: 'Approve', params: { approval_id: 'invalid' } },
      ],
    };
    render(<MessageBubble message={message} />);
    expect(screen.getByText('Verified author review link is unavailable.')).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Review document author consent' })).toBeNull();
    expect(screen.queryByRole('button', { name: /perform action: approve/i })).toBeNull();
  });

});
