import { describe, expect, it } from 'vitest';
import { observeChatSseBody } from '../../src/app/api/_lib/sse-stream-integrity';

const encode = (s: string) => new TextEncoder().encode(s);

async function collect(source: ReadableStream<Uint8Array>): Promise<string> {
  const reader = source.getReader();
  const decoder = new TextDecoder();
  let result = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      result += decoder.decode(value, { stream: true });
    }
    return result + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

function stream(...parts: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const part of parts) controller.enqueue(encode(part));
      controller.close();
    },
  });
}

describe('Next.js chat SSE transport integrity', () => {
  it('passes through successful split upstream SSE bytes without alteration', async () => {
    const output = await collect(observeChatSseBody(
      stream(
        'data: {"type":"content","content":"Hello"}\n\n',
        'data: {"type":"complete","content":""}\n\n',
        'data: [DO', 'NE]\n\n',
      ),
      'corr-1',
    ));
    expect(output).toBe(
      'data: {"type":"content","content":"Hello"}\n\n' +
      'data: {"type":"complete","content":""}\n\n' +
      'data: [DONE]\n\n',
    );
    expect(output).not.toContain('CHAT_STREAM_UPSTREAM_TERMINATED');
  });

  it('reports an empty HTTP-200 SSE body as upstream termination', async () => {
    const output = await collect(observeChatSseBody(stream(), 'corr-2'));
    expect(output).toContain('"error_code":"CHAT_STREAM_UPSTREAM_TERMINATED"');
    expect(output).toContain('"correlation_id":"corr-2"');
    expect(output).not.toContain('"type":"complete"');
  });

  it('reports a status-only stream as backend termination', async () => {
    const output = await collect(observeChatSseBody(
      stream('data: {"type":"status","content":"Working"}\n\n'),
      'corr-3',
    ));
    expect(output).toContain('"type":"status"');
    expect(output).toContain('"error_code":"CHAT_STREAM_UPSTREAM_TERMINATED"');
    expect(output).not.toContain('"type":"complete"');
  });

  it('reports an interrupted body as transport failure without leaked details', async () => {
    let pullCount = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (pullCount++ === 0) {
          controller.enqueue(encode('data: {"type":"status","content":"Working"}\n\n'));
        } else {
          controller.error(new Error('sensitive upstream socket failure'));
        }
      },
    });
    const output = await collect(observeChatSseBody(body, 'corr-4'));
    expect(output).toContain('CHAT_STREAM_UPSTREAM_INTERRUPTED');
    expect(output).toContain('corr-4');
    expect(output).not.toContain('sensitive upstream socket failure');
  });

  it('does not treat a bare upstream DONE marker as model-generated text', async () => {
    const output = await collect(observeChatSseBody(
      stream('data: [DONE]\n\n'), 'corr-5',
    ));
    expect(output).toBe('data: [DONE]\n\n');
  });
});
