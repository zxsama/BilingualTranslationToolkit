"""Track only catalog overrides created by this Toolkit."""

import hashlib
import json
from pathlib import Path
import re

from .locale_registry import atomic_write

STATE = "override.json"
BACKUP = "original-language.mo"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def restore_override(root, state_dir):
    root, state_dir = Path(root), Path(state_dir)
    state, backup = state_dir / STATE, state_dir / BACKUP
    if not state.is_file():
        return
    meta = json.loads(state.read_text(encoding="utf-8"))
    code = meta["locale"]
    if not re.fullmatch(r"[A-Za-z0-9_@-]+", code) or code == "bilingual":
        raise ValueError("Invalid tracked locale")
    path = root / code / "LC_MESSAGES" / "blender.mo"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Tracked locale is outside the user locale directory")
    # If another tool edited the catalog after us, their data wins.
    if path.is_file() and _digest(path.read_bytes()) == meta["digest"]:
        if meta["had_original"]:
            content = backup.read_bytes()
            atomic_write(path, "wb", lambda file: file.write(content))
        else:
            path.unlink()
    state.unlink()
    if backup.is_file():
        backup.unlink()


def apply_override(root, state_dir, code, catalog):
    root, state_dir = Path(root), Path(state_dir)
    path = root / code / "LC_MESSAGES" / "blender.mo"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Locale is outside the user locale directory")
    restore_override(root, state_dir)
    backup = state_dir / BACKUP
    had_original = path.is_file()
    if had_original:
        original = path.read_bytes()
        atomic_write(backup, "wb", lambda file: file.write(original))
    meta = {"locale": code, "digest": _digest(catalog), "had_original": had_original}
    atomic_write(state_dir / STATE, "w", lambda file: json.dump(meta, file))
    atomic_write(path, "wb", lambda file: file.write(catalog))
