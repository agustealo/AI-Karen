# AI KAREN UI Authority

> **Status:** Canonical UI location contract
> **Applies to:** web UI development, frontend CI, deployment, testing, and agent/code navigation

AI KAREN currently has one canonical user-facing frontend in this repository:

```text
src/ui_launchers/Karen-AI-Theme/
```

That Next.js application is the frontend authority unless `PROJECT_DEV_MANIFEST.md` is updated to declare a replacement.

## Canonical frontend

| Responsibility | Canonical owner |
|---|---|
| Web application | `src/ui_launchers/Karen-AI-Theme/` |
| Frontend source | `src/ui_launchers/Karen-AI-Theme/src/` |
| Browser journey tests | `src/ui_launchers/Karen-AI-Theme/e2e/` |
| Frontend package contract | `src/ui_launchers/Karen-AI-Theme/package.json` |
| Production web image | `src/ui_launchers/Karen-AI-Theme/Dockerfile.production` |
| Production-mock refusal check | `src/ui_launchers/Karen-AI-Theme/tools/check-no-prod-mocks.sh` |
| Frontend CI | `.github/workflows/main-quality-gate.yml` and release workflows |

## Retired paths

The following historical paths are not current frontend authorities and must not be used for new development, CI, documentation, or agent task routing unless they are explicitly reintroduced through an architectural change:

```text
src/ui_launchers/web_ui/
src/ui_launchers/desktop_ui/
src/ui_launchers/common/
src/ui_launchers/KAREN-Theme-Default/
ui_launchers/web_ui/
ui_launchers/desktop_ui/
ui_launchers/KAREN-Theme-Default/
```

Do not create compatibility copies or replacement directories at these locations to satisfy stale imports or instructions. Update stale references to the canonical frontend instead.

## Architectural boundary

The UI displays backend/runtime truth. It does not own provider selection, prompt assembly, model availability, memory recall policy, plugin execution authority, RBAC enforcement, fallback model text, or persistence truth.

The canonical request direction is:

```text
Karen-AI-Theme
    |
    v
backend API
    |
    v
Runtime
    |
    +--> CORTEX decisions
    +--> canonical provider/model runtime
    +--> governed memory/tool/extension execution
```

Frontend code may present controls for backend-governed capabilities, but it must consume authoritative backend contracts rather than recreating routing or fallback logic locally.

## Development

From the repository root:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm ci
npm run dev
```

The package currently defines the application development server on port `3000`.

## Required verification

Before frontend changes are considered merge-ready, run:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm ci --no-audit --no-fund
npm run ci:forbid-mocks
npm run typecheck
npx vitest run --passWithNoTests
npm run build
```

Release candidates additionally prove the first-run browser journey and production container build through `.github/workflows/beta-release-gate.yml`.

## Source-of-truth rule

When older README files, sprint sheets, pasted paths, or historical implementation notes disagree with this file, verify the live repository and `PROJECT_DEV_MANIFEST.md`. Do not resurrect deleted UI trees merely because an old document names them.
