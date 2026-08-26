from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
service = ROOT / "src/ai_karen_engine/services/identity_vault/credential_vault_service.py"
text = service.read_text()
old = "from sqlalchemy import select, and_, or_, func\n"
new = "from sqlalchemy import select, and_, or_, func, text\n"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("unexpected SQLAlchemy import shape in CredentialVaultService")
service.write_text(text)

print("=== identity vault DTO definition census ===")
for token in ["class CredentialCreate", "class CredentialResponse", "class AuditEventType", "class LoginStatus", "class TokenRotationResult"]:
    hits = []
    for path in ROOT.rglob("*.py"):
        if path == service:
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        if token in content:
            hits.append(str(path.relative_to(ROOT)))
    print(token, hits)

expected_dto = ROOT / "src/ai_karen_engine/database/models/identity_vault.py"
print("expected DTO module exists:", expected_dto.exists())
print("review fix complete")
