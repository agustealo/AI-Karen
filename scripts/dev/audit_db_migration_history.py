from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"

files = sorted(MIGRATIONS.glob("*.sql"))
print(f"migration_count={len(files)}")

name_flags = Counter()
verbs = Counter()
table_create = defaultdict(list)
table_alter = defaultdict(list)
table_drop = defaultdict(list)
rls = defaultdict(list)
extensions = defaultdict(list)

repair_words = re.compile(r"(fix|correct|repair|converg|cleanup|populate|backfill|patch|legacy|compat|expand)", re.I)
create_table = re.compile(r"\bCREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w.\"]+)", re.I)
alter_table = re.compile(r"\bALTER\s+TABLE(?:\s+IF\s+EXISTS)?\s+([\w.\"]+)", re.I)
drop_table = re.compile(r"\bDROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+([\w.\"]+)", re.I)

for path in files:
    text = path.read_text(encoding="utf-8", errors="replace")
    name = path.name
    if repair_words.search(name):
        name_flags["repair_named"] += 1
        print(f"repair_named={name}")
    if re.search(r"\bDROP\s+(TABLE|COLUMN|TYPE|INDEX|POLICY)\b", text, re.I):
        name_flags["destructive_sql"] += 1
        print(f"destructive_sql={name}")
    if re.search(r"\bUPDATE\b", text, re.I):
        name_flags["data_update"] += 1
    if re.search(r"\bDELETE\b", text, re.I):
        name_flags["data_delete"] += 1
    if re.search(r"\bCREATE\s+EXTENSION\b", text, re.I):
        name_flags["extension_sql"] += 1
    if re.search(r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", text, re.I):
        name_flags["rls_sql"] += 1

    for match in create_table.finditer(text):
        table_create[match.group(1).strip('"')].append(name)
    for match in alter_table.finditer(text):
        table_alter[match.group(1).strip('"')].append(name)
    for match in drop_table.finditer(text):
        table_drop[match.group(1).strip('"')].append(name)
    for match in re.finditer(r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", text, re.I):
        rls[name].append("enable")
    for match in re.finditer(r"CREATE\s+EXTENSION(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w\"]+)", text, re.I):
        extensions[match.group(1).strip('"')].append(name)

print("\n=== SUMMARY ===")
for key, value in sorted(name_flags.items()):
    print(f"{key}={value}")
print(f"created_tables={len(table_create)}")
print(f"altered_tables={len(table_alter)}")
print(f"dropped_tables={len(table_drop)}")

print("\n=== MULTI-TOUCH TABLES ===")
for table in sorted(set(table_create) | set(table_alter) | set(table_drop)):
    touches = len(table_create[table]) + len(table_alter[table]) + len(table_drop[table])
    if touches > 1:
        print(f"{table}: create={table_create[table]} alter={table_alter[table]} drop={table_drop[table]}")

print("\n=== TABLE CREATION ===")
for table, names in sorted(table_create.items()):
    print(f"{table}: {names}")

print("\n=== EXTENSIONS ===")
for ext, names in sorted(extensions.items()):
    print(f"{ext}: {names}")

# Search schema mutation outside canonical migration authority.
print("\n=== OUTSIDE MIGRATION DDL ===")
for path in (ROOT / "src").rglob("*.py"):
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"create_all\s*\(|\bCREATE\s+TABLE\b|\bALTER\s+TABLE\b|\bDROP\s+TABLE\b", text, re.I):
        print(path.relative_to(ROOT))

print("\n=== SQL OUTSIDE CANONICAL MIGRATIONS ===")
for path in ROOT.rglob("*.sql"):
    if MIGRATIONS in path.parents:
        continue
    print(path.relative_to(ROOT))
