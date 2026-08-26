from pathlib import Path

path = Path("src/ai_karen_engine/api_routes/training/data.py")
text = path.read_text(encoding="utf-8")

field = '    tenant_id: Optional[str] = Field(None, description="Tenant scope for curated memory")\n'
if field not in text:
    raise SystemExit("curated dataset tenant override field not found")
text = text.replace(field, "", 1)

old = '        tenant_id = request.tenant_id or current_user.tenant_id or current_user.user_id\n'
new = '''        tenant_id = current_user.tenant_id\n        if not tenant_id or str(tenant_id) == "default":\n            raise HTTPException(\n                status_code=403,\n                detail="Explicit tenant scope is required for curated memory datasets",\n            )\n'''
if old not in text:
    raise SystemExit("curated dataset tenant resolution seam not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
