"""Conservative selectors for Blender's global (msgctxt, msgid) catalog."""

from collections import defaultdict
import json
from pathlib import Path

DEFAULT_CONTEXT = "*"


def key(context, text):
    return context or DEFAULT_CONTEXT, text


def read_terms(path):
    """Old lists still accept plain text. 'Context :: Text' matches one key."""
    plain, exact = set(), set()
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            context, separator, text = line.partition(" :: ")
            if separator and context.strip() and text.strip():
                exact.add(key(context.strip(), text.strip()))
            else:
                plain.add(line)
    return plain, exact


def _enum_labels(prop):
    return {key(prop.translation_context, item.name)
            for item in prop.enum_items_static if item.identifier and item.name}


def _node_source_keys(version):
    if len(version) < 2:
        return {}
    path = Path(__file__).parent / "resource/bilingual_translator" / f"node_keys_{version[0]}_{version[1]}.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def collect_area_keys(types, version=()):
    """Use actual RNA/UI labels, never guesses derived from Python identifiers."""
    sections = defaultdict(set)
    modifier_panel = {"DATA_PT_modifiers", "DATA_PT_gpencil_modifiers"}
    node_headers = {"NODE_MT_view", "NODE_MT_select", "NODE_MT_add", "NODE_MT_node"}
    for name in dir(types):
        cls = getattr(types, name, None)
        if not isinstance(cls, type):
            continue

        if cls not in (types.Menu, types.Panel) and issubclass(cls, (types.Menu, types.Panel)):
            label = getattr(cls, "bl_label", "")
            if not label:
                continue
            label_key = key(getattr(cls, "bl_translation_context", None), label)
            if name.startswith("TOPBAR_MT_") and issubclass(cls, types.Menu):
                sections["topbar"].add(label_key)
            elif name in node_headers and issubclass(cls, types.Menu):
                sections["node_headers"].add(label_key)
            elif (name in modifier_panel or name.startswith("OBJECT_MT_modifier_add")):
                sections["modifiers"].add(label_key)
            elif (
                issubclass(cls, types.Panel)
                and getattr(cls, "bl_space_type", "") == "PROPERTIES"
                and getattr(cls, "bl_region_type", "") == "WINDOW"
            ):
                sections["properties"].add(label_key)
            continue

        if issubclass(cls, types.Modifier):
            area = "modifiers"
        elif cls is not types.Node and issubclass(cls, types.Node):
            area = "node_properties"
        else:
            continue
        rna = cls.bl_rna
        # Do not guess property labels from Python identifiers.
        inherited = {prop.identifier for prop in rna.base.properties} if rna.base else set()
        for prop in rna.properties:
            if prop.identifier in inherited or prop.translation_context == "Do not translate":
                continue
            if area == "modifiers" and prop.is_hidden:
                continue
            if prop.name:
                sections[area].add(key(prop.translation_context, prop.name))
            if prop.type == "ENUM":
                sections[area].update(_enum_labels(prop))

    sections["modifiers"].update(_enum_labels(types.Modifier.bl_rna.properties["type"]))
    for context, labels in _node_source_keys(version).get("properties", {}).items():
        sections["node_properties"].update(key(context, label) for label in labels)
    if len(version) >= 2:
        asset_keys = Path(__file__).parent / "resource/bilingual_translator/modifier_asset_labels.json"
        with asset_keys.open(encoding="utf-8") as handle:
            assets = json.load(handle)
        series = ".".join(str(part) for part in version[:2])
        sections["modifier_asset_keys"].update(key(None, label) for label in assets.get(series, ()))
        sections["modifiers"].update(sections["modifier_asset_keys"])
    # Modifier menus belong to the Properties editor: selecting Properties
    # includes modifiers, but selecting Modifiers alone does not include panels.
    return sections


def scoped_keys(available, sections, selected, whitelist=((), ())):
    selected = set(selected)
    if "properties" in selected:
        selected.add("modifiers")
    # Any selected area can opt a key in. Identical keys are shared globally
    # by Blender, so they remain bilingual wherever they are used.
    chosen = set().union(*(sections.get(area, set()) for area in selected)) & available
    if selected & {"nodes", "node_properties"}:
        # Some unrelated controls share an identical global catalog key with
        # a node header. Preserve the user-requested header exclusion here.
        chosen.difference_update(sections.get("node_headers", ()))

    first_level, descendants = set(), set()
    for area, prefix in (("nodes", "node"), ("modifiers", "modifier")):
        if area in selected:
            first_level.update(sections.get(f"{prefix}_menu_root", ()))
            descendants.update(sections.get(f"{prefix}_menu_deeper", ()))
    # A selected submenu takes priority at all locations sharing its exact
    # Blender translation key; unrelated panels/properties do not opt it in.
    chosen.difference_update(first_level - descendants)

    plain, exact = whitelist
    if plain and not selected:
        by_label = defaultdict(set)
        for item in available:
            if item[1] in plain:
                by_label[item[1]].add(item)
        # A plain extra augments a manual whitelist-only catalog only if it
        # resolves to a single non-default key. Combined with areas, old plain
        # lists must not silently opt other UI areas back in.
        chosen.update(next(iter(items)) for items in by_label.values()
                      if len(items) == 1 and next(iter(items))[0] != DEFAULT_CONTEXT)
    return chosen | (available & set(exact))
