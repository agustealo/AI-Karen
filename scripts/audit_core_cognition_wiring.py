from __future__ import annotations

from pathlib import Path

ROOT = Path('.')
PACKAGES = [
    'adaptive',
    'cortex',
    'expression',
    'intelligence',
    'contracts',
    'context',
    'reasoning',
]
SEARCH_ROOTS = [Path('src'), Path('tests'), Path('scripts'), Path('.github')]
SKIP = {Path('scripts/audit_core_cognition_wiring.py')}


def iter_text_files():
    for base in SEARCH_ROOTS:
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if not path.is_file() or path in SKIP:
                continue
            if any(part in {'.git', '__pycache__', 'node_modules'} for part in path.parts):
                continue
            if path.suffix.lower() not in {'.py', '.md', '.yml', '.yaml', '.toml', '.json', '.txt'}:
                continue
            try:
                yield path, path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue


files = list(iter_text_files())
print('CORE COGNITION WIRING CENSUS')
print('=============================')

for pkg in PACKAGES:
    pkg_path = Path('src/ai_karen_engine/core') / pkg
    print(f'\n## {pkg}')
    print(f'exists={pkg_path.exists()}')
    if pkg_path.exists():
        py_files = sorted(pkg_path.rglob('*.py'))
        print(f'python_files={len(py_files)}')

    needles = [
        f'ai_karen_engine.core.{pkg}',
        f'core.{pkg}',
    ]
    hits = []
    for path, text in files:
        if any(n in text for n in needles):
            if pkg_path.exists() and path.is_relative_to(pkg_path):
                continue
            hits.append(path)
    print(f'external_reference_files={len(set(hits))}')
    for path in sorted(set(hits))[:100]:
        print(f'  REF {path}')

print('\n## named authority references')
for symbol in [
    'AdaptiveRuntime',
    'CortexExecutionDecider',
    'evaluate_cortex',
    'dispatch(',
    'IntelligenceRuntime',
    'get_intelligence_runtime',
    'ExpressionGateway',
    'ReasoningExecutor',
    'KROOrchestrator',
    'get_kro_orchestrator',
    'builtin_transformers',
    'builtin_vllm',
]:
    hits = []
    for path, text in files:
        if symbol in text:
            hits.append(path)
    print(f'\n{symbol}: {len(set(hits))} files')
    for path in sorted(set(hits))[:100]:
        print(f'  {path}')

print('\n## authority-risk terms by package')
for pkg in PACKAGES:
    pkg_path = Path('src/ai_karen_engine/core') / pkg
    if not pkg_path.exists():
        continue
    terms = {
        'provider_selection': ['provider', 'model_registry', 'get_registry(', 'fallback_order'],
        'tool_execution': ['execute_plan', 'tool execution', 'execute_tool', 'plugin execution'],
        'memory_persistence': ['memory_writes', 'persist', 'writeback', 'memory write'],
        'runtime_orchestration': ['orchestrator', 'execution_mode', 'route_request', 'langgraph'],
    }
    joined = '\n'.join(
        p.read_text(encoding='utf-8', errors='ignore')
        for p in pkg_path.rglob('*.py')
        if p.is_file()
    ).lower()
    for category, words in terms.items():
        matched = [w for w in words if w.lower() in joined]
        if matched:
            print(f'{pkg}: {category}: {matched}')
