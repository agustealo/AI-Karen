import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ChatIntelligenceSidecar from '@/components/chat/ChatIntelligenceSidecar';

describe('ChatIntelligenceSidecar', () => {
  it('renders backend runtime, memory, and learning truth without inventing values', () => {
    render(
      <ChatIntelligenceSidecar
        metadata={{
          actual_provider: 'builtin_vllm',
          actual_model: 'qwen3',
          runtime_engine: 'vllm',
          response_source: 'provider_runtime',
          latency_ms: 842,
          fallback_level: 0,
          context_used: true,
          memory_recall_count: 4,
          memory_persistence_status: 'stored',
          trajectory_id: 'trajectory-1234567890',
          policy_decision_id: 'policy-1234567890',
          decision_observation_id: 'decision-1234567890',
          feature_snapshot_count: 1,
          execution_status: 'success',
          persistence_success: true,
        }}
        agentSteps={[]}
        configuredProvider="builtin_vllm"
        configuredModel="qwen3"
      />,
    );

    expect(screen.getByText('KAREN Intelligence')).toBeTruthy();
    expect(screen.getAllByText('builtin_vllm').length).toBeGreaterThan(0);
    expect(screen.getAllByText('qwen3').length).toBeGreaterThan(0);
    expect(screen.getByText('842 ms')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();
    expect(screen.getByText('stored')).toBeTruthy();
    expect(screen.getByText('success')).toBeTruthy();
    expect(screen.getByText('primary path')).toBeTruthy();
  });

  it('shows unavailable state instead of synthetic ML or memory metrics', () => {
    render(
      <ChatIntelligenceSidecar
        metadata={{}}
        agentSteps={[]}
      />,
    );

    expect(
      screen.getByText(/has not reported memory recall or formation evidence/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/learning lineage or outcome evidence has not been reported/i),
    ).toBeTruthy();
    expect(
      screen.getByText(/no agent or tool activity has been reported/i),
    ).toBeTruthy();
  });
});
