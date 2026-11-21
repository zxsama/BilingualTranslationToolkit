"""Labels supplied by Blender's native Essentials-library Add submenus."""

from pathlib import Path


def collect_node_asset_keys(datafiles, libraries, *, with_levels=False):
    if not datafiles:
        return (set(), set()) if with_levels else set()
    root = Path(datafiles) / "assets"
    folders = sorted((root / "nodes").glob("*.blend"))
    if not folders:
        return (set(), set()) if with_levels else set()
    first = {("*", "Unassigned"), ("*", "Loading Asset Libraries")}
    deeper = set()
    for path in folders:
        try:
            # assets_only excludes helper datablocks. Do not assign data_to:
            # no asset is linked/appended and no project data is touched.
            with libraries.load(str(path), assets_only=True) as (data_from, _data_to):
                deeper.update(("*", name) for name in data_from.node_groups)
        except (OSError, RuntimeError, TypeError):
            # Older builds or a damaged/missing Essentials library must not
            # prevent generating the rest of the translations.
            continue
    catalog = root / "blender_assets.cats.txt"
    if catalog.is_file():
        try:
            for line in catalog.read_text(encoding="utf-8-sig").splitlines():
                fields = line.strip().split(":", 2)
                if len(fields) != 3 or line.lstrip().startswith("#"):
                    continue
                parts = fields[1].split("/")
                if parts[0] in {"Shading", "Compositing", "Geometry Nodes", "Hair"}:
                    # The native menu gets the catalog basename, not its
                    # descriptive catalog name. Editor prefixes are stripped.
                    if parts[0] == "Hair":
                        first.add(("*", "Hair"))
                        deeper.update(("*", part) for part in parts[1:] if part)
                    elif len(parts) > 1:
                        first.add(("*", parts[1]))
                        deeper.update(("*", part) for part in parts[2:] if part)
        except (OSError, UnicodeError):
            pass
    return (first, deeper) if with_levels else first | deeper
