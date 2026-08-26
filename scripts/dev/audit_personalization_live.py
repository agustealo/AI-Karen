from __future__ import annotations
from pathlib import Path
import ast

ROOT = Path('.')
PKG = ROOT / 'src/ai_karen_engine/core/personalization'
TOKENS = [
    'UserModelRuntime','PersonalizationRepository','PreferenceRecord','PreferenceCandidate',
    'BehaviorPattern','UserGoal','GoalState','UserModel','SelfModel','RelationshipModel',
    'ResolvedPreferences','CurrentUserState','PreferenceEvidenceStore','BehaviorAggregator',
]

print('=== FILES ===')
for p in sorted(PKG.rglob('*.py')):
    print(p)

print('\n=== TOP LEVEL SURFACE ===')
for p in sorted(PKG.rglob('*.py')):
    try:
        tree=ast.parse(p.read_text(encoding='utf-8'))
    except Exception as exc:
        print('PARSE_ERROR', p, exc); continue
    defs=[]
    for n in tree.body:
        if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            defs.append(n.name)
    if defs: print(p, ':', ', '.join(defs))

print('\n=== EXTERNAL REFERENCES ===')
all_py=[p for p in ROOT.rglob('*.py') if '.git' not in p.parts]
for token in TOKENS:
    refs=[]
    for p in all_py:
        if PKG in p.parents or p == PKG:
            continue
        try: text=p.read_text(encoding='utf-8',errors='ignore')
        except Exception: continue
        if token in text:
            refs.append(str(p))
    print(token, len(refs))
    for r in refs[:50]: print(' ',r)

print('\n=== PACKAGE IMPORT REFERENCES ===')
for p in all_py:
    if PKG in p.parents: continue
    try: text=p.read_text(encoding='utf-8',errors='ignore')
    except Exception: continue
    if 'core.personalization' in text:
        print(p)
