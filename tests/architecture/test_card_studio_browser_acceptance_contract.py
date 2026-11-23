"""Source-level contract for the opt-in real-host Card Studio acceptance path.

These tests prove that the protected workflow *can* dispatch the genuine
browser suite and does not leak account recordings. They are NOT a substitute
for executing the suite against an approved authenticated deployment.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "src/ui_launchers/Karen-AI-Theme"
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"


def test_card_studio_reuses_protected_browser_workflow() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "          - card-studio\n" in workflow
    assert "authenticated-settings-visual-acceptance:" in workflow
    assert "inputs.scenario == 'card-studio'" in workflow
    assert "vars.KAREN_CARD_STUDIO_ACCEPTANCE_URL" in workflow
    assert "KAREN_CARD_STUDIO_MUTATION_APPROVED" in workflow
    assert "Require disposable preview approval for persistent Card Studio acceptance" in workflow
    assert 'test "$SELECTED_TARGET" = "preview"' in workflow
    assert 'test "$KAREN_CARD_STUDIO_MUTATION_APPROVED" = "true"' in workflow
    assert "scripts/ci/verify_vercel_deployment.py" in workflow
    assert "scripts/ci/verify_deployment_revision.py" in workflow
    assert "Reattest deployed provenance and current main after browser proof" in workflow
    assert "card-studio-live-acceptance.spec.ts" in workflow
    assert "--project=chromium --reporter=list --retries=0" in workflow
    assert 'KAREN_CARD_STUDIO_SANITIZED_CAPTURE: "false"' in workflow
    assert 'test -n "$KAREN_UX_ISOLATION_EMAIL"' in workflow
    assert 'test -n "$KAREN_UX_ISOLATION_PASSWORD"' in workflow
    assert 'KAREN_UX_ISOLATION_EMAIL: ${{ secrets.KAREN_UX_ISOLATION_EMAIL }}' in workflow
    assert 'KAREN_UX_ISOLATION_PASSWORD: ${{ secrets.KAREN_UX_ISOLATION_PASSWORD }}' in workflow
    # Card Studio uses the existing protected settings job. The shared fixture
    # must run before real credentials are typed into a Vercel preview.
    assert 'KAREN_SETTINGS_VERIFIED_DEPLOYMENT: "true"' in workflow
    assert 'VERCEL_AUTOMATION_BYPASS_SECRET: ${{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}' in workflow


def test_card_studio_browser_spec_does_not_forge_authenticated_responses() -> None:
    spec = (THEME / "e2e/card-studio-live-acceptance.spec.ts").read_text(
        encoding="utf-8"
    )
    assert 'import { expect, test } from "./fixtures/verified-search-deployment";' in spec
    assert 'import { expect, test, type Page' not in spec
    assert "signInApprovedKaren" in spec
    assert "page.route(" in spec
    assert "route.fetch({ maxRetries: 0 })" in spec
    assert 'await route.abort("failed")' in spec
    assert "route.fulfill(" not in spec
    assert "page.addInitScript(" not in spec
    assert "storageState:" not in spec
    assert 'trace: "off", screenshot: "off", video: "off"' in spec
    assert 'test.skip(!enabled,' in spec
    assert "process.env.KAREN_CARD_STUDIO_MUTATION_APPROVED" in spec
    assert 'result.receipt.idempotency_key' in spec
    assert "const viewports = [" in spec
    for width in (390, 768, 1024, 1440):
        assert f"width: {width}," in spec
    assert 'expect(actualPosts).toBe(1)' in spec
    assert 'expect(replay.request).toEqual(lostRequest)' in spec
    assert 'expect(conflict.status(), "Stale tab must receive actual backend CAS 409").toBe(409)' in spec


def test_card_studio_protects_credential_bearing_playwright_evidence() -> None:
    config = (THEME / "e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert "const cardStudioAcceptance =" in config
    assert "cardStudioAcceptance;" in config
    assert "pinReadbackAcceptance || cardStudioAcceptance ? 0" in config
    assert "documentAuthorAcceptance || cardStudioAcceptance" in config
    assert "screenshot: privateBrowserRun ? 'off'" in config
    assert "video: privateBrowserRun" in config
    assert "trace: privateBrowserRun" in config

    doc = (THEME / "e2e/README.md").read_text(encoding="utf-8")
    assert "KGUI-CARD-STUDIO-01E" in doc
    assert "KARI_ENABLE_CARD_STUDIO_CRUD=true" in doc
    assert "default remains" in doc
    assert "operator" in doc


def test_card_studio_uses_existing_scoped_protection_cookie_before_login() -> None:
    """A direct Playwright import would strand preview acceptance at Vercel SSO."""
    fixture = (THEME / "e2e/fixtures/verified-search-deployment.ts").read_text(
        encoding="utf-8"
    )
    spec = (THEME / "e2e/card-studio-live-acceptance.spec.ts").read_text(
        encoding="utf-8"
    )
    assert 'import { expect, test } from "./fixtures/verified-search-deployment";' in spec
    assert "export const test = base.extend<" in fixture
    assert "approvedDeploymentAccess:" in fixture
    assert "KAREN_SETTINGS_VERIFIED_DEPLOYMENT" in fixture
    assert "VERCEL_AUTOMATION_BYPASS_SECRET" in fixture
    assert "context.request.get(approved.origin," in fixture
    assert "'x-vercel-protection-bypass': bypassSecret" in fixture
    assert "'x-vercel-set-bypass-cookie': 'true'" in fixture
    assert "cookie.name === '_vercel_jwt'" in fixture
    assert "cookie.domain.replace(/^\\./, '') === approved.hostname" in fixture
    assert "if (response.status() >= 400 || !sessionEstablished)" in fixture
    assert "await use();" in fixture
    assert "route.fulfill(" not in fixture
    assert "page.addInitScript(" not in fixture


def test_card_studio_real_second_principal_denies_all_owner_paths() -> None:
    """No same-user stale tab or client-faked identity counts as authorization."""
    spec = (THEME / "e2e/card-studio-live-acceptance.spec.ts").read_text(
        encoding="utf-8"
    )
    assert 'KCARD-LIVE-ISOLATION: second real user' in spec
    assert 'process.env.KAREN_UX_ISOLATION_EMAIL' in spec
    assert 'process.env.KAREN_UX_ISOLATION_PASSWORD' in spec
    assert 'email.trim().toLowerCase() === isolationEmail.trim().toLowerCase()' in spec
    assert 'await browser.newContext({' in spec
    assert 'serviceWorkers: "block"' in spec
    assert 'cookie.name === "_vercel_jwt"' in spec
    assert 'await otherContext.addCookies(accessCookies)' in spec
    assert 'await signInApprovedKaren(other, isolationEmail, isolationPassword,' in spec
    assert 'await openStudio(other, origin.origin)' in spec
    assert 'foreignUserId !== ownerUserId' in spec
    assert 'const foreignCreated = await verifiedCommit(' in spec
    assert 'const foreignId = foreignCreated.saved.template.template_id' in spec
    assert 'item.template_id === foreignId' in spec
    assert 'await archiveOwned(other, origin.origin, foreignId, 1)' in spec
    assert 'foreignInventory.status).toBe(200)' in spec
    assert 'ownerId + "/revisions"' in spec
    assert 'ownerId + "/revisions/1"' in spec
    assert 'method: "PUT"' in spec
    assert 'method: "POST"' in spec
    assert 'expect([403, 404]' in spec
    assert 'ownerTemplate.template.revision).toBe(1)' in spec
    assert 'await archiveOwned(page, origin.origin, ownerId, 1)' in spec
    assert 'localStorage.getItem("access_token")' in spec
    assert 'url.origin !== window.location.origin' in spec
    assert 'credentials: "same-origin"' in spec
    assert 'redirect: "error"' in spec
    assert 'page.route(' in spec  # Response loss only; not foreign auth.
    assert 'route.fulfill(' not in spec
    assert 'page.addInitScript(' not in spec
    assert 'trace: "off", screenshot: "off", video: "off"' in spec
