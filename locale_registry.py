"""Blender locale registry and portable catalog writes."""

from pathlib import Path
import os
from tempfile import NamedTemporaryFile


def read_languages(path):
    """Read both old 3-field and newer 4-field Blender language registries."""
    languages = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        fields = line.split(":")
        if len(fields) < 3 or not fields[0].isdigit() or not fields[2]:
            continue  # Old registries have category heading rows with no code.
        number = int(fields[0])
        languages[number] = (number, fields[1], fields[2])
    return tuple(languages[number] for number in sorted(languages))


def atomic_write(path, mode, write):
    """Publish only a complete registry/catalog. Never truncate a prior file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    options = {"encoding": "utf-8"} if mode == "w" else {}
    with NamedTemporaryFile(mode=mode, dir=path.parent, delete=False, **options) as handle:
        temporary = Path(handle.name)
        try:
            write(handle)
        except BaseException:
            handle.close()
            temporary.unlink()
            raise
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def register_locale(path, entry):
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    _, _, code = entry.split(":")
    if path.exists() and any(row[2] == code for row in read_languages(path)):
        return
    # Place a complete line even when the shipped file has no final newline.
    atomic_write(path, "w", lambda f: f.write(text.rstrip("\r\n") + "\n" + entry + "\n"))


def remove_locale(path, locale):
    """Remove only the requested locale, preserving other lines and comments."""
    path = Path(path)
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8-sig")
    def keep(line):
        fields = line.split(":")
        return not (len(fields) >= 3 and fields[0].isdigit() and fields[2].strip() == locale)
    updated = "".join(line for line in text.splitlines(keepends=True) if keep(line))
    if updated != text:
        atomic_write(path, "w", lambda f: f.write(updated))


def refresh_locale_aliases(path, official_path):
    """Update renamed stock IDs in a copied registry without replacing user rows."""
    path = Path(path)
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8-sig")
    official = {row[0]: row[2] for row in read_languages(official_path)}
    aliases = {"zh_CN": "zh_HANS", "zh_TW": "zh_HANT"}
    existing = {row[2] for row in read_languages(path)}
    def update(line):
        fields = line.rstrip("\r\n").split(":")
        if len(fields) < 3 or not fields[0].isdigit():
            return line
        new = aliases.get(fields[2])
        if new and new not in existing and official.get(int(fields[0])) == new:
            fields[2] = new
            return ":".join(fields) + ("\n" if line.endswith(("\r", "\n")) else "")
        return line
    updated = "".join(map(update, text.splitlines(keepends=True)))
    if updated != text:
        atomic_write(path, "w", lambda f: f.write(updated))
