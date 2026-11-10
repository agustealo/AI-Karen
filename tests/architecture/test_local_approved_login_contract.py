"""Shared approved login cannot silently widen credential destinations."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e"
LOGIN = E2E / "fixtures/approved-karen-login.ts"
CHAT = E2E / "copilotkit-consumer-boot.spec.ts"


def test_login_defaults_to_https_and_requires_explicit_local_consent() -> None:
    source = LOGIN.read_text(encoding="utf-8")
    assert 'options: Readonly<{ allowLocalLoopback?: boolean }> = {}' in source
    for guard in (
        'options.allowLocalLoopback === true',
        'process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1"',
        'process.env.KAREN_CHAT_BOOT_ACCEPTANCE !== "1"',
        'approved.protocol === "http:"',
        'approved.protocol === "https:"',
        'approved.port === ""',
        'approved.port !== ""',
        '["127.0.0.1", "localhost"].includes(approved.hostname)',
        'approved.pathname === "/"',
        '!approved.username && !approved.password',
        '!approved.search && !approved.hash',
    ):
        assert guard in source


def test_credential_entry_requires_verified_origin_before_and_after_login() -> None:
    source = LOGIN.read_text(encoding="utf-8")
    expected = "expect(new URL(page.url()).origin).toBe(approved.origin);"
    assert source.count(expected) == 2
    first = source.index(expected)
    email = source.index('page.getByRole("textbox", { name: "Email" }).fill(email)')
    password = source.index('page.getByLabel("Password").fill(password)')
    submit = source.index('page.getByRole("button", { name: "Sign in", exact: true }).click()')
    last = source.rindex(expected)
    assert source.index('page.goto(new URL("/login", approved).toString())') < first
    assert first < email < password < submit < last
    assert "page.route(" not in source
    assert "route.fulfill(" not in source


def test_local_http_permission_is_not_given_to_other_consumer_suites() -> None:
    source = CHAT.read_text(encoding="utf-8")
    optin = "signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode })"
    assert source.count(optin) == 4
    assert 'const localMode = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1"' in source
    assert 'if (releaseMode && localMode)' in source
    assert 'await requireLiveCanonicalBackend(page, target)' in source
    for filename in (
        "karen-copilotkit-protocol-acceptance.spec.ts",
        "karen-copilotkit-native-acceptance.spec.ts",
        "karen-durable-history-restoration.spec.ts",
    ):
        other = (E2E / filename).read_text(encoding="utf-8")
        assert "allowLocalLoopback" not in other
