from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "src/ai_karen_engine/extensions/platform/core/integration/models.py"
text = path.read_text()
block = '''\n\n# Database utility functions\ndef create_extension_tables(engine):\n    \"\"\"Create all extension-related tables.\"\"\"\n    Base.metadata.create_all(engine)\n\n\ndef drop_extension_tables(engine):\n    \"\"\"Drop all extension-related tables.\"\"\"\n    Base.metadata.drop_all(engine)\n'''
if block not in text:
    raise SystemExit("extension schema helper block not found")
text = text.replace(block, "\n")
text = text.replace('    "create_extension_tables",\n', "")
text = text.replace('    "drop_extension_tables",\n', "")
path.write_text(text)

if "metadata.create_all" in text or "metadata.drop_all" in text:
    raise SystemExit("extension runtime DDL survived")
print("removed zero-consumer extension schema mutation helpers")
