"""Extract menu labels from Blender's shipped Python UI without running draws."""

import ast


def _literal_strings(expr):
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        return _literal_strings(expr.body) | _literal_strings(expr.orelse)
    if isinstance(expr, ast.Call) and _method(expr) in {"n_", "pgettext_n"} and expr.args:
        return _literal_strings(expr.args[0])
    return set()


def _context(expr, contexts):
    if expr is None:
        return None
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        if expr.value.id in {"i18n_contexts", "contexts"}:
            return getattr(contexts, expr.attr, None) or "*"
    strings = _literal_strings(expr)
    return next(iter(strings)) if len(strings) == 1 else None


def _operator_rna(ops, identifier):
    if "_OT_" in identifier:
        namespace, _, name = identifier.partition("_OT_")
        identifier = f"{namespace.lower()}.{name}"
    namespace, separator, name = identifier.partition(".")
    if not separator or not namespace.isidentifier() or not name.isidentifier():
        return None
    try:
        return getattr(getattr(ops, namespace), name).get_rna_type()
    except (AttributeError, KeyError, RuntimeError):
        return None


def _call_keys(call, types, ops, contexts):
    method = getattr(call.func, "attr", getattr(call.func, "id", ""))
    kw = {item.arg: item.value for item in call.keywords}
    if method in {"iface_", "pgettext_iface"}:
        expr = call.args[0] if call.args else kw.get("msgid")
        ctx = call.args[1] if len(call.args) > 1 else kw.get("msgctxt")
        value = _context(ctx, contexts)
        if ctx is None or value is not None:
            yield from ((value or "*", label) for label in _literal_strings(expr) if label)
        return
    if isinstance(kw.get("translate"), ast.Constant) and not kw["translate"].value:
        return
    expr = kw.get("text")
    if method == "label" and expr is None and call.args:
        expr = call.args[0]
    ids = _literal_strings(call.args[0]) if call.args else set()
    context = _context(kw.get("text_ctxt"), contexts)
    if "text_ctxt" in kw and context is None:
        return
    if method in {"operator", "operator_menu_enum", "operator_enum"}:
        for identifier in ids:
            rna = _operator_rna(ops, identifier)
            if rna is None:
                continue
            if method in {"operator_menu_enum", "operator_enum"} and len(call.args) > 1:
                for prop_id in _literal_strings(call.args[1]):
                    prop = rna.properties.get(prop_id)
                    if prop is not None and prop.type == "ENUM":
                        yield from ((prop.translation_context or "*", item.name)
                                    for item in prop.enum_items_static if item.identifier and item.name)
            if method != "operator_enum":
                for label in _literal_strings(expr) if expr is not None else {rna.name}:
                    if label:
                        yield (context or rna.translation_context or "*", label)
    elif method == "menu":
        if expr is not None:
            yield from ((context or "*", label) for label in _literal_strings(expr) if label)
        else:
            for identifier in ids:
                cls = getattr(types, identifier, None)
                label = getattr(cls, "bl_label", "")
                if label:
                    yield (getattr(cls, "bl_translation_context", None) or "*", label)
    elif method == "label":
        yield from ((context or "*", label) for label in _literal_strings(expr) if label)
    elif method in {
        "node_operator", "add_node_type",
        "node_operator_with_outputs", "add_node_type_with_outputs",
        "node_operator_with_searchable_enum", "add_node_type_with_searchable_enum",
        "node_operator_with_searchable_enum_socket", "add_node_type_with_searchable_enum_socket",
    }:
        # Plain helpers take (layout, node_type). The enhanced helpers take
        # (context, layout, node_type, ...) and delegate the primary menu row
        # to the plain helper. Search-result suffixes are not menu rows.
        position = 1 if method in {"node_operator", "add_node_type"} else 2
        arg = kw.get("node_type", kw.get("node_idname"))
        if arg is None and len(call.args) > position:
            arg = call.args[position]
        for identifier in _literal_strings(arg):
            rna = types.Node.bl_rna_get_subclass(identifier)
            if rna:
                explicit = kw.get("label")
                for label in _literal_strings(explicit) if explicit is not None else {rna.name}:
                    if label:
                        yield (rna.translation_context or "*", label)
    elif method in {"operator_modifier_add", "operator_modifier_add_asset"} and len(call.args) > 1:
        prop = types.Modifier.bl_rna.properties["type"]
        if method == "operator_modifier_add_asset":
            labels = _literal_strings(call.args[1])
        elif "text" in kw:
            labels = _literal_strings(kw["text"])
        else:
            labels = {item.name for identifier in _literal_strings(call.args[1])
                      if (item := prop.enum_items_static.get(identifier))}
        yield from ((prop.translation_context or "*", label) for label in labels if label)
    elif method in {"color_mix_node", "add_color_mix_node"}:
        # These helpers call iface_("Mix Color") before passing the label.
        yield ("*", "Mix Color")



def _class_draws(path):
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {cls.name: tuple(
        call for method in cls.body
        if isinstance(method, ast.FunctionDef) and method.name.startswith("draw")
        for call in ast.walk(method) if isinstance(call, ast.Call)
    ) for cls in tree.body if isinstance(cls, ast.ClassDef)}


def _shipped_addon_draws(root):
    # Only the shipped modules known to add rows to the Add menu. Parse
    # their source, and use it only when the live menu carries the callback.
    # Never discover or execute arbitrary add-on files here.
    addon_specs = (
        ("node_wrangler.interface", ("node_wrangler", "interface.py"),
         {"multipleimages_menu_func", "attr_nodes_add_menu_func", "NWAttributeMenuBase"}),
        ("io_scene_gltf2.blender.com.gltf2_blender_ui",
         ("io_scene_gltf2", "blender", "com", "gltf2_blender_ui.py"),
         {"add_gltf_settings_to_menu"}),
    )
    sources = {}
    for module, relative, owners in addon_specs:
        for folder in ("addons_core", "addons"):
            path = root.parent.parent.joinpath(folder, *relative)
            if not path.is_file():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            sources[module] = {
                node.name: tuple(call for call in ast.walk(node) if isinstance(call, ast.Call))
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in owners
            }
            break
    return sources


def _method(call):
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def _old_node_categories(path, types):
    # Older releases use these shipped lists, not Python menu classes.
    if not path.is_file():
        return
    for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(call, ast.Call) or len(call.args) == 0:
            continue
        method = _method(call)
        if method in {"ShaderNodeCategory", "TextureNodeCategory", "CompositorNodeCategory"}:
            if len(call.args) > 1:
                yield from ((False, ("*", label)) for label in _literal_strings(call.args[1]) if label)
        elif method == "NodeItem":
            explicit = next((kw.value for kw in call.keywords if kw.arg == "label"), None)
            if explicit is not None:
                yield from ((True, ("*", label)) for label in _literal_strings(explicit) if label)
                continue
            for identifier in _literal_strings(call.args[0]):
                rna = types.Node.bl_rna_get_subclass(identifier)
                if rna and rna.name:
                    yield (True, (rna.translation_context or "*", rna.name))


def _stock_menu_draws(cls, sources):
    # Blender wraps Menu.draw after append/prepend. In that case the wrapper
    # belongs to _bpy_types, not to the class that implements the stock menu.
    # Recover only the shipped draw functions and resolve their owning class
    # in the right module, or recognize the narrow bundled add-on allowlist.
    draw = getattr(cls, "draw", None)
    for func in getattr(draw, "_draw_funcs", (draw,)):
        module = getattr(func, "__module__", "")
        owner = getattr(func, "__qualname__", "").split(".")[0]
        yield from sources.get(module, {}).get(owner, ())


def _node_add_items(root, types, ops, contexts):
    sources = {
        f"bl_ui.{path.stem}": _class_draws(path)
        for path in (root / "space_node.py", root / "node_add_menu.py", *root.glob("node_add_menu_*.py"))
    }
    sources.update(_shipped_addon_draws(root))
    # Boolean depth suffices, but a menu drawn at both levels must be
    # visited twice. menu_contents inlines a draw without adding a level.
    visited, todo = set(), [("NODE_MT_add", False)]
    while todo:
        name, deeper = todo.pop()
        if (name, deeper) in visited:
            continue
        visited.add((name, deeper))
        cls = getattr(types, name, None)
        if cls is None:
            continue
        for call in _stock_menu_draws(cls, sources):
            method = _method(call)
            if method in {"menu", "menu_contents"} and call.args:
                todo.extend((target, deeper or method == "menu")
                            for target in _literal_strings(call.args[0]))
            elif method == "draw_menu":
                path_expr = call.args[1] if len(call.args) > 1 else next(
                    (kw.value for kw in call.keywords if kw.arg == "path"), None)
                menu_map = getattr(cls, "pathing_dict", None) or {}
                for path in _literal_strings(path_expr):
                    target = menu_map.get(path)
                    if target:
                        todo.append((target, True))
                        item = getattr(types, target, None)
                        label = getattr(item, "bl_label", "")
                        if label:
                            yield deeper, (getattr(item, "bl_translation_context", None) or "*", label)
            elif method in {"draw_group_menu", "draw_node_group_add_menu"}:
                for identifier in ("NodeGroupInput", "NodeGroupOutput"):
                    rna = types.Node.bl_rna_get_subclass(identifier)
                    if rna and rna.name:
                        yield deeper, (rna.translation_context or "*", rna.name)
                if method == "draw_group_menu":
                    yield deeper, ("*", "New Group")
                    linked = (getattr(cls, "pathing_dict", None) or {}).get("Group/Linked")
                    if linked:
                        todo.append((linked, True))
                        item = getattr(types, linked, None)
                        label = getattr(item, "bl_label", "")
                        if label:
                            yield deeper, (getattr(item, "bl_translation_context", None) or "*", label)
            elif method == "draw_node_categories_menu":
                for inner, item in _old_node_categories(root.parent / "nodeitems_builtins.py", types):
                    yield deeper or inner, item
            elif method in {
                "repeat_zone", "closure_zone", "simulation_zone", "for_each_element_zone", "typed_bundle",
                "add_repeat_zone", "add_closure_zone", "add_simulation_zone", "add_foreach_geometry_element_zone",
            }:
                expr = next((kw.value for kw in call.keywords if kw.arg == "label"),
                            call.args[1] if len(call.args) > 1 else None)
                yield from ((deeper, ("*", label)) for label in _literal_strings(expr) if label)
            yield from ((deeper, item) for item in _call_keys(call, types, ops, contexts))


def _modifier_add_items(root, types, ops, contexts, draws):
    path = root / "properties_data_modifier.py"
    draws_by_module = {f"bl_ui.{path.stem}": draws}
    visited, todo = set(), [("OBJECT_MT_modifier_add", False)]
    while todo:
        name, deeper = todo.pop()
        if (name, deeper) in visited:
            continue
        visited.add((name, deeper))
        cls = getattr(types, name, None)
        if cls is None:
            continue
        if name == "OBJECT_MT_modifier_add":
            yield False, (getattr(cls, "bl_translation_context", None) or "*", cls.bl_label)
        for call in _stock_menu_draws(cls, draws_by_module):
            method = _method(call)
            if method in {"menu", "menu_contents"} and call.args:
                targets = _literal_strings(call.args[0])
                todo.extend((target, deeper or method == "menu") for target in targets)
                if not deeper and "OBJECT_MT_modifier_add_root_catalogs" in targets:
                    # Native root catalogs with shipped modifier assets.
                    yield from ((False, ("*", label)) for label in (
                        "Geometry", "Hair", "Instances", "Simulation", "Unassigned", "Loading Asset Libraries",
                    ))
            yield from ((deeper, item) for item in _call_keys(call, types, ops, contexts))


def collect_root_menu_keys(root, types, ops, contexts):
    nodes = {item for deeper, item in _node_add_items(root, types, ops, contexts) if not deeper}
    draws = _class_draws(root / "properties_data_modifier.py")
    modifiers = {item for deeper, item in _modifier_add_items(root, types, ops, contexts, draws) if not deeper}
    return nodes, modifiers


def collect_menu_items(root, types, ops, contexts):
    mod_draws = _class_draws(root / "properties_data_modifier.py")
    for section, draws, names in (
        ("topbar", _class_draws(root / "space_topbar.py"), lambda n: n.startswith("TOPBAR_MT_")),
        ("modifiers", mod_draws,
         lambda n: n.startswith("OBJECT_MT_modifier_add") or n in {"DATA_PT_modifiers", "DATA_PT_gpencil_modifiers"}),
    ):
        for name, calls in draws.items():
            if names(name):
                for call in calls:
                    for context, label in _call_keys(call, types, ops, contexts):
                        if context != "Do not translate":
                            yield section, (context, label)
    for scope, layers in (
        ("node", _node_add_items(root, types, ops, contexts)),
        ("modifier", _modifier_add_items(root, types, ops, contexts, mod_draws)),
    ):
        for deeper, item in layers:
            if item[0] != "Do not translate":
                yield f"{scope}_menu_{'deeper' if deeper else 'root'}", item


def optional_node_menu_translations(types, language_code):
    """Known add-on labels that are not in Blender's stock catalog."""
    if language_code not in {"zh_CN", "zh_HANS"}:
        return {}
    menu = getattr(types, "NODE_MT_template_add", None)
    root = getattr(types, "NODE_MT_add", None)
    owner_is_node_presets = (
        menu is not None and menu.__module__.rsplit(".", 1)[-1] == "node_presets"
    )
    if owner_is_node_presets and any(
        callback.__module__ == menu.__module__ and callback.__name__ == "add_node_button"
        for callback in getattr(getattr(root, "draw", None), "_draw_funcs", ())
    ):
        # This extension sets text explicitly but does not set text_ctxt.
        return {
            ("*", "Template"): "模板",
            ("*", "Set search dir in the addon-prefs"): "请在插件偏好设置中指定搜索目录",
        }
    return {}
