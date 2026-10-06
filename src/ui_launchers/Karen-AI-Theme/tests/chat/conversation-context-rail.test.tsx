import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ConversationContextRail from '@/components/chat/ConversationContextRail';
import type { AgentStepEvent } from '@/lib/types';

describe('ConversationContextRail', () => {
  it('renders canonical continuity and capability receipts without inventing access', () => {
    const metadata = {
      proactive_continuity: {
        candidates: [
          {
            id: 'loop-1',
            subject: 'Follow up on the interview',
            source_type: 'open_loop',
            urgency: 'high',
            confidence: 0.97,
            utility: 0.91,
          },
        ],
      },
      continuity_primary_candidate_id: 'loop-1',
      continuity_ambiguous: false,
      capability_receipt: {
        allowed_capabilities: ['memory.read'],
        forbidden_capabilities: ['external.write'],
        allowed_tools: ['calendar.lookup'],
        allowed_plugins: ['calendar'],
        allowed_agents: ['planner'],
        requires_human_gate: false,
        requires_resumability: true,
      },
    };

    render(
      <ConversationContextRail
        metadata={metadata}
        agentSteps={[]}
      />,
    );

    expect(screen.getByText('Follow up on the interview')).toBeTruthy();
    expect(screen.getByText('primary')).toBeTruthy();
    expect(screen.getByText('calendar.lookup')).toBeTruthy();
    expect(screen.getByText('calendar')).toBeTruthy();
    expect(screen.getByText('planner')).toBeTruthy();
    expect(screen.getByText('memory.read')).toBeTruthy();
    expect(screen.getByText('external.write')).toBeTruthy();
  });

  it('surfaces ambiguity and human gates as attention instead of auto-executing', () => {
    render(
      <ConversationContextRail
        metadata={{
          proactive_continuity: {
            candidates: [
              {
                id: 'loop-1',
                subject: 'Finish the estimate',
                source_type: 'open_loop',
              },
              {
                id: 'loop-2',
                subject: 'Book the hotel',
                source_type: 'open_loop',
              },
            ],
          },
          continuity_ambiguous: true,
          capability_receipt: {
            requires_human_gate: true,
          },
        }}
        agentSteps={[]}
      />,
    );

    expect(screen.getByText('Needs you')).toBeTruthy();
    expect(
      screen.getByText(/more than one unfinished thread is plausible/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/requires a human approval before execution can continue/i),
    ).toBeTruthy();
  });

  it('shows only execution activity that the runtime actually reported', () => {
    const steps: AgentStepEvent[] = [
      {
        type: 'tool_execution_completed',
        step_id: 'tool-1',
        metadata: { tool: 'web.search' },
      },
      {
        type: 'extension_execution_completed',
        step_id: 'plugin-1',
        metadata: { extension_id: 'research' },
      },
      {
        type: 'agent_step_completed',
        step_id: 'provider-1',
        metadata: { actual_provider: 'builtin_vllm' },
      },
    ];

    render(
      <ConversationContextRail
        metadata={{}}
        agentSteps={steps}
      />,
    );

    expect(screen.getByText('web.search')).toBeTruthy();
    expect(screen.getByText('research')).toBeTruthy();
    expect(screen.getByText('builtin_vllm')).toBeTruthy();
    expect(
      screen.getByText(/no request-scoped capability receipt was reported yet/i),
    ).toBeTruthy();
  });

  it('surfaces durable approval recovery states without inventing execution', () => {
    const { rerender } = render(
      <ConversationContextRail
        metadata={{}}
        agentSteps={[]}
        approvals={[
          {
            approval_id: 'approval-1',
            intent: 'external_action',
            risk_level: 'high',
            status: 'pending',
            expires_at: '2026-10-06T14:00:00Z',
          },
        ]}
        approvalsLoadState="ready"
      />,
    );

    expect(screen.getByText('Needs you')).toBeTruthy();
    expect(
      screen.getByText(/external action is waiting for your decision/i),
    ).toBeTruthy();
    expect(screen.getByText(/approval required/i)).toBeTruthy();
    expect(screen.getByText(/high risk/i)).toBeTruthy();

    rerender(
      <ConversationContextRail
        metadata={{}}
        agentSteps={[]}
        approvals={[
          {
            approval_id: 'approval-1',
            intent: 'external_action',
            risk_level: 'high',
            status: 'approved',
            expires_at: '2026-10-06T14:00:00Z',
          },
        ]}
        approvalsLoadState="ready"
      />,
    );

    expect(
      screen.getByText(/external action is approved and ready to resume/i),
    ).toBeTruthy();
    expect(screen.getByText(/ready to resume/i)).toBeTruthy();
  });

  it('distinguishes unavailable approval truth from an empty approval list', () => {
    render(
      <ConversationContextRail
        metadata={{}}
        agentSteps={[]}
        approvals={[]}
        approvalsLoadState="unavailable"
      />,
    );

    expect(screen.getByText('Needs you')).toBeTruthy();
    expect(
      screen.getByText(/approval state is unavailable/i),
    ).toBeTruthy();
  });

});
