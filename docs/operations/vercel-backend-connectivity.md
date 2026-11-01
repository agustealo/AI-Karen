# Vercel frontend to canonical AI-Karen backend

**Owner:** Deployment and runtime configuration. The Next.js frontend does not host
or emulate Karen's Python/FastAPI runtime.

## Deployment topology and source of truth

Karen's canonical backend is the FastAPI app in
`src/ai_karen_engine/app.py`. Its required-dependency readiness authority
is `GET /ready` in
`src/ai_karen_engine/api_routes/monitoring/probes.py`; it requires
configuration and PostgreSQL availability. Optional model/provider degradation
does not by itself make PostgreSQL-backed consumer state ready.

Local/Docker installs use the Compose service name `http://api:8000` *within
the Docker network*. That hostname, `host.docker.internal`, localhost and
loopback addresses **cannot serve as an ordinary Vercel function's backend**
because Vercel runs in a separate network. A READY Vercel Next.js deployment
only proves compilation and static/web-function deployment, not backend access.

For Vercel Preview and Production, configure the existing server-only
`KAREN_BACKEND_URL` environment variable to the **actual, separately deployed,
network-reachable canonical FastAPI origin**. Use HTTPS for internet-routed
backends, TLS verification and server-side authentication; a deliberately
private, routed deployment must have its own verified private connectivity.
Never substitute `NEXT_PUBLIC_*`, `API_BASE_URL`, or arbitrary Docker
fallback URLs for this authority. Do not place usernames, tokens, credentials,
path suffixes or query parameters inside the backend-origin setting.

The backend requires its own deploy, networking, PostgreSQL and provider
runtime. Vercel's Next.js deployment does not start a local FastAPI process,
PostgreSQL container or local model server. Do not disable authentication,
publish a raw database connection, or create fake model responses to turn
a connectivity failure into HTTP 200.

## November 1, 2026 incident: evidence and resolution gate

- Exact-head Preview `35e948babe67e314a3280f47702c73e0db31a678`
  served `/api/deployment-revision` at 200 but `/api/health` at 502.
- A later diagnostic Preview logged
  `target_scope=loopback`, `configuration_source=default`,
  `cause_code=ECONNREFUSED` for `GET /ready`. This is proof the
  **deployed Vercel function was not receiving a usable configured backend
  origin** and attempted its local default instead.
- A Vercel project environment-variable *entry* named `KAREN_BACKEND_URL`
  is not proof the function received a nonempty value. Sensitive values are
  not printed, disclosed or inferred from redacted connector responses.
- The checked production frontend also returned HTTP 502 for health. The
  preview log identifies the preview's root cause; the older production
  deployment's complete target configuration has not been independently proven.

The Vercel proxy now fails closed with a structured configuration error for a
missing, invalid, insecure or Docker-only origin rather than attempting its
loopback default. This diagnostic **does not deploy the missing backend**.

## Operator verification

1. Verify the real FastAPI host is running and its `GET /ready` answers
   HTTP 200 with `ready: true`, `status: ready`, and components
   `configuration: ready` and `database: ready`. A generic monitoring
   `/api/health` response, even at HTTP 200, is not sufficient.
2. Verify the chosen origin is reachable **from the Vercel serverless
   network**, not merely from a Docker container or developer machine. Keep
   transport encrypted and protect the backend from unauthorized requests.
3. In the `ai-karen` Vercel project's environment settings, supply the
   exact server-only `KAREN_BACKEND_URL` for the intended Preview and
   Production targets. Confirm the right branch-specific overrides and
   redeploy to get a new immutable deployment with those values.
4. On that exact immutable deployed URL, independently verify
   `GET /api/deployment-revision` reports the reviewed full Git commit,
   and `GET /api/health` returns HTTP 200 with exactly
   `{"status":"ok","backend_ready":true}` and `Cache-Control: no-store`.
   Any 503, 502 or redirect blocks acceptance.
5. Only then run the existing protected `copilotkit-consumer` Playwright
   acceptance on the reviewed exact revision. It must prove real model
   execution, provenance, Stop/cancellation, saved drafts, rendered replies,
   restored history, and no disabled inspector-chunk loads.
6. Review Vercel runtime logs for `canonical_upstream_unavailable`,
   `target_scope`, `configuration_source`, and a sanitized `cause_code`.
   The diagnostic deliberately excludes actual URLs and secret values.

**Release rule:** Docker first-boot smoke, Vercel READY state and GitHub quality
gates are separate from live backend and authenticated browser acceptance.
A consumer release must not pass while any of these independent live checks
fails. Never broaden deployment protection or replay a mutating chat request
against an alternate host to work around missing backend connectivity.
