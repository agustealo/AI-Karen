from __future__ import annotations

import runpy
from pathlib import Path

path = Path(__file__).with_name("apply_context_converge1.py")
text = path.read_text(encoding="utf-8")
old = '    text = replace_once(text, needle, replacement, f"{relative} canonical prompt handoff")\n'
new = '''    if needle not in text:\n        raise RuntimeError(f"{relative} canonical prompt handoff: target not found")\n    text = text.replace(needle, replacement, 1)\n'''
if text.count(old) != 1:
    raise RuntimeError("could not patch converge-1 provider handoff transform")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
runpy.run_path(str(path), run_name="__main__")
