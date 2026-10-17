# KOC-04G: Governed channel host startup

Karen's FastAPI lifespan, not an HTTP route or the Telegram plugin, owns
channel host initialization. **Disabled by default**. Turning on the host
injects audited dependencies into explicitly installed channel transport
adapters; it does **not** activate tenant connections or send messages.

## Operator configuration

All settings are validated centrally by
`src/ai_karen_engine/config/channels.py`.

| Variable | Default | Contract |
| --- | --- | --- |
| `KAREN_CHANNEL_HOST_ENABLED` | `false` | Explicit opt-in to construct a channel host |
| `KAREN_CHANNEL_HOST_INSTALLATIONS_JSON` | `{}` | JSON map of installed transport ID to the exact Identity Vault secret types needed by that transport; required if enabled |
| `KAREN_CHANNEL_SERVICE_PRINCIPAL_ID` | empty | Required configured service actor for auditable Vault secret reads |
| `KAREN_CHANNEL_HTTP_TIMEOUT_SECONDS` | `10` | Bound outgoing HTTP client timeout to 0.5–60 seconds |
| `KAREN_CHANNEL_MAX_BODY_BYTES` | `65536` | Bound native webhook request bytes to 1–10,485,760 |

An example registry shape (NOT a valid or enabled connection):

```json
{"telegram-bot": ["bot_token", "webhook_secret"]}
```

Real encrypted secret values remain only in the tenant-scoped Identity Vault.
References must use canonical `vault://<credential-uuid>` handles. Never put bot
tokens, webhook secrets, or arbitrary secret-bearing URL query arguments in
`.env`, channel manifests, logger metadata, or channel SQL tables.

## Runtime ownership

1. When disabled, application startup constructs **no** channel host and the
   native webhook returns 503.
2. When enabled, canonical FastAPI lifespan loads and validates the registry
   configuration, builds or borrows a canonical `PluginKernel` and Identity
   Vault, and initializes `ChannelHostServices`.
3. Each configured installation is verified against the existing plugin
   registry and the same canonical loader instance. The host injects only a
   provider-scoped `ChannelVaultSecretResolver` and an HTTP client configured
   with timeouts and `trust_env=False`. Secrets are fetched later by the
   Vault, audited and decrypted only there.
4. `ChannelIngressService` becomes visible to the HTTP route **only after**
   every dependency has initialized successfully. Partial startup shuts down
   what was created. A malformed registry or missing plugin fails startup
   instead of silently switching to a different channel.
5. Shutdown first unmounts ingress, then closes native adapters and HTTP,
   releases owned resources, and finally allows the existing database teardown.
   Borrowed PluginKernel/Vault dependencies remain owned by their provider.

## Safety gate and deliberately unimplemented operations

No tenant connection is automatically started by this release. A persisted
`enabled=true` connection alone is **not** process authorization to resume a
Telegram adapter after restart. The host must explicitly reconcile current
tenant authorization, credential revision, installed transport and host
ownership before attempting a restart or external send. Until then, provider
requests fail closed instead of silently running under stale authorization.

This PR does not register Telegram webhooks with Telegram, provision bot
credentials, expose admin lifecycle routes, claim durable inbox work, execute
ChatRuntime from the API route, or deliver outbox messages. These are separate
governed stages and need live PostgreSQL, restart, replay, and native transport
verification before being represented as operational.

## Proof

```bash
python -m compileall src
ruff check src tests
pytest tests/extensions/test_channel_host_lifecycle.py -q
pytest tests/extensions/ -q
pytest tests/architecture/ -q
```

Main Quality, Production First-Boot, authentication, plugin-backend, and database contract workflows remain binding release gates.
