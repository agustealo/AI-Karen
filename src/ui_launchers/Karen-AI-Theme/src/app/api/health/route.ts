import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '../_lib/backend-proxy';

/**
 * Health Check Route
 *
 * Proxies health checks to the canonical backend monitoring endpoint to determine
 * if services are ready. This is used by the frontend to wait for backend
 * initialization before making other API calls.
 */
export const GET = async (request: Request) => {
  try {
    const nextRequest = new NextRequest(request.url, {
      method: 'GET',
      headers: request.headers,
    });

    const response = await proxyToBackend(
      nextRequest,
      '/api/health',
      { longTimeout: false }
    );

    if (response.status === 200) {
      return NextResponse.json({ status: 'ok', backend_ready: true });
    }

    return response;
  } catch (error) {
    console.warn('[HealthCheck] Backend not ready:', error);
    return NextResponse.json(
      {
        status: 'initializing',
        backend_ready: false,
        message: 'Backend services are still initializing'
      },
      { status: 503 }
    );
  }
};
