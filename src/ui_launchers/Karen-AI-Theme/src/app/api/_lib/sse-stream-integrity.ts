/**
 * Transport-only integrity boundary for the canonical chat SSE proxy.
 *
 * The FastAPI owner terminates a normal stream with "data: [DONE]".
 * A 200 body that closes before that marker is a transport failure, not
 * proof that any model generated an answer. Preserve the upstream chunks
 * untouched and append only a safe, correlated SSE error on interruption.
 */
export function observeChatSseBody(
  upstream: ReadableStream<Uint8Array>,
  correlationId: string,
  signal?: AbortSignal,
): ReadableStream<Uint8Array> {
  const reader = upstream.getReader();
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let trailingText = '';
  let receivedBytes = 0;
  let released = false;

  const releaseReader = () => {
    if (!released) {
      released = true;
      reader.releaseLock();
    }
  };

  const emitFailure = (
    controller: ReadableStreamDefaultController<Uint8Array>,
    code: 'CHAT_STREAM_UPSTREAM_TERMINATED' | 'CHAT_STREAM_UPSTREAM_INTERRUPTED',
  ) => {
    console.error('[ChatStreamProxy] upstream_stream_incomplete', {
      correlation_id: correlationId,
      error_code: code,
      received_bytes: receivedBytes,
    });
    const errorPayload = {
      type: 'error',
      content: 'The backend stream ended before completion.',
      correlation_id: correlationId,
      metadata: {
        error_code: code,
        error_type: 'UpstreamStreamFailure',
        correlation_id: correlationId,
        response_source: 'stream_proxy',
        received_bytes: receivedBytes,
      },
    };
    controller.enqueue(
      encoder.encode(`\n\ndata: ${JSON.stringify(errorPayload)}\n\n`),
    );
  };

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) {
          trailingText += decoder.decode();
          // This is the *backend* transport marker, not a fabricated model
          // completion. Every canonical FastAPI SSE outcome ends with it.
          if (!/(?:^|\r?\n)data:[ \t]*\[DONE\]\r?\n\r?\n$/.test(trailingText)) {
            if (!signal?.aborted) {
              emitFailure(controller, 'CHAT_STREAM_UPSTREAM_TERMINATED');
            }
          }
          controller.close();
          releaseReader();
          return;
        }

        if (value) {
          receivedBytes += value.byteLength;
          trailingText = (trailingText + decoder.decode(value, { stream: true }))
            .slice(-256);
          controller.enqueue(value);
        }
      } catch (error) {
        if (signal?.aborted) {
          controller.error(error);
        } else {
          emitFailure(controller, 'CHAT_STREAM_UPSTREAM_INTERRUPTED');
          controller.close();
        }
        releaseReader();
      }
    },
    async cancel(reason) {
      try {
        await reader.cancel(reason);
      } finally {
        releaseReader();
      }
    },
  });
}
