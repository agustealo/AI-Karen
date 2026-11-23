# Time Query Plugin

Time Query is the app-wide time authority for current time, world clocks, saved clocks, stopwatches, alarms, and timezone conversion.

## Source ownership

- `plugin_manifest.json` is the executable backend contract. It declares `handler:MainExtension`, plugin capabilities, allowed roles, and the conversational action policy. It must not contain the GUI `entry` object.
- `manifest.json` is the frontend presentation contract. Its `entry.entry_file` declares `TimeQueryPage.tsx` and is independently validated before any governed UI publication.
- `ui/` is the canonical source for Time Query's React page, hooks, services, types, and components. The tracked `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/time-query/` package is a published frontend projection, not a separate source to edit.
- Backend plugin admission remains owned by the extension registry and runtime. GUI metadata never grants Python execution, permissions, or RBAC eligibility.

## Runtime behavior

The UI uses the existing `usePluginExtension('time-query')` host. It renders an explicit host error or loading state until the governed backend capability is ready. All requests use `TimeQueryApi` and the host's authenticated execution interface.

The client coalesces/serializes read-only requests and honors bounded retry information on HTTP 429 responses. State-changing actions (alarm and clock mutations) are **not automatically retried**, and an unconfirmed mutation does not report success. The stopwatch UI does not flood the backend with a 100 ms polling loop.

## Verification

The source-to-projection parity and clean publication contracts are in `tests/extensions/test_time_query_ui_source_authority.py`. They verify the real validated manifest, the canonical entry component, the governed UI materializer and restart installer, and that published assets match the source that owns them.

Run:

```bash
pytest tests/extensions/test_time_query_ui_source_authority.py -q
pytest tests/extensions/test_time_query_ingress_contract.py -q
```

Frontend typecheck and production build remain mandatory for UI changes.
