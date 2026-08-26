from pathlib import Path

path = Path("src/ai_karen_engine/core/runtime/chat_runtime.py")
text = path.read_text(encoding="utf-8")

old_import = '''        from ai_karen_engine.core.runtime.prompt import (\n            PromptAssemblyRequest,\n            get_prompt_assembler,\n        )'''
new_import = '''        from ai_karen_engine.core.runtime.prompt import (\n            PromptAssemblyRequest,\n            get_prompt_runtime_service,\n        )'''
old_call = "result = await get_prompt_assembler().assemble(assembly_request)"
new_call = "result = await get_prompt_runtime_service().assemble_prompt(assembly_request)"

if old_import not in text:
    raise SystemExit("expected ChatRuntime prompt import block not found")
if old_call not in text:
    raise SystemExit("expected ChatRuntime assembler call not found")

text = text.replace(old_import, new_import, 1)
text = text.replace(old_call, new_call, 1)
path.write_text(text, encoding="utf-8")
