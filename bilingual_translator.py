import re
import shutil
import bpy
import os
import bpy.app.translations as trs
from pathlib import Path
from .lib import polib
from .translations import CHINESE_ID, LANGUAGE_CODES, SYSTEM_LOCALE, register_ui_translations
from .locale_registry import atomic_write, read_languages, refresh_locale_aliases, register_locale, remove_locale
from .locale_override import apply_override, restore_override
from .translation_areas import collect_area_keys, key, read_terms, scoped_keys
from .builtin_menu_keys import collect_menu_items, optional_node_menu_translations
from .node_menu_assets import collect_node_asset_keys

# Blender 5.3 removed CHECK_PRINTF_FORMAT from its private i18n settings.
# Keep the legacy matches so the appended translation cannot add arguments.
_LEGACY_PRINTF_FORMAT = (
    r"(?!<%)(?:%%)*%"
    r"[-+#0]?"
    r"(?:\*|[0-9]+)?"
    r"(?:\.(?:\*|[0-9]+))?"
    r"(?:[hljztL]|hh|ll)?"
    r"[tldiuoxXfFeEgGaAcspn]"
)
_APPENDED_FORMAT = re.compile(
    _LEGACY_PRINTF_FORMAT
    + r"|\{[^{}]*\}"
)

class BilingualTranslatorData:
    def __init__(self):
        self.lang_idx = 99
        self.menu_name = "Bilingual (双语显示)"
        self.locale_name = "bilingual"
        self.local_locale = SYSTEM_LOCALE
        self.user_locale = bpy.utils.user_resource("DATAFILES", path="locale")

    def initialize(self):
        source = Path(self.local_locale)
        destination = Path(self.user_locale)
        if not self.local_locale or not (source / "languages").is_file():
            raise OSError("The corresponding language pack does not exist!")
        if not self.user_locale or source.resolve() == destination.resolve():
            raise OSError("The user locale directory must be separate from Blender's shipped locale.")
        for file in source.rglob("*"):
            if file.is_file():
                target = destination / file.relative_to(source)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
        self.refresh_aliases()
        register_locale(self.get_cfg_file(), self.get_cfg_append_data())
        Path(self.get_bilingual_mo_path()[0]).mkdir(parents=True, exist_ok=True)

    def source_catalog(self, code):
        if not self.local_locale:
            raise OSError("The corresponding language pack does not exist!")
        root = Path(self.local_locale)
        for directory in dict.fromkeys((code, code.split("_")[0])):
            catalog = root / directory / "LC_MESSAGES" / "blender.mo"
            if catalog.is_file():
                return directory, catalog
        raise OSError("The corresponding language pack does not exist!")

    def get_user_locale_floder(self):
        return self.user_locale

    def get_local_locale_floder(self):
        return self.local_locale

    def get_cfg_append_data(self):
        return f"{self.lang_idx}:{self.menu_name}:{self.locale_name}"

    def get_cfg_file(self):
        return os.path.join(self.user_locale, "languages")

    def get_bilingual_mo_path(self):
        new_mo_floder = os.path.join(self.user_locale, self.locale_name)
        new_mo_lcm = os.path.join(new_mo_floder, "LC_MESSAGES")
        new_mo_file = os.path.join(new_mo_lcm, "blender.mo")
        return new_mo_lcm, new_mo_file

    def get_used_language_code(self):
        bili_mo_floder, _ = self.get_bilingual_mo_path()
        code_path = os.path.join(bili_mo_floder, "language_code")
        language_code = ""
        if os.path.exists(code_path):
            with open(code_path, "r") as f:
                language_code = f.read()
        return code_path, language_code

    def get_whitelist_path(self):
        addon_path = os.path.dirname(__file__)
        return os.path.join(addon_path, "resource", "bilingual_translator", "whitelist")

    def get_blacklist_path(self):
        addon_path = os.path.dirname(__file__)
        return os.path.join(addon_path, "resource", "bilingual_translator", "blacklist")

    def refresh_aliases(self):
        if self.local_locale and self.user_locale:
            refresh_locale_aliases(self.get_cfg_file(), Path(self.local_locale) / "languages")

    def ensure_stock_catalog(self, locale_folder, source_catalog):
        destination = Path(self.user_locale) / locale_folder / "LC_MESSAGES" / "blender.mo"
        if not destination.is_file():
            atomic_write(destination, "wb", lambda file: file.write(source_catalog.read_bytes()))

    def get_bilingual_init_state(self):
        if not self.user_locale:
            return False
        config = Path(self.get_cfg_file())
        return config.is_file() and any(row[2] == self.locale_name for row in read_languages(config))

    def remove_generated_locale(self):
        if not self.user_locale or not self.local_locale or Path(self.user_locale).resolve() == Path(self.local_locale).resolve():
            raise ValueError("The user locale directory must be separate from Blender's shipped locale.")
        folder = Path(self.get_bilingual_mo_path()[0])
        if not folder.resolve().is_relative_to(Path(self.user_locale).resolve()):
            raise ValueError("Toolkit locale is outside the user locale directory")
        restore_override(self.user_locale, folder)
        remove_locale(self.get_cfg_file(), self.locale_name)
        for name in ("blender.mo", "language_code"):
            path = folder / name
            if path.is_file():
                path.unlink()
        for path in (folder, folder.parent):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    def get_bilingual_compile_state(self):
        _, bil_mo_file = self.get_bilingual_mo_path()
        if os.path.exists(bil_mo_file):
            return True
        else:
            return False


class MZ_OT_RegisterBilingualTranslator(bpy.types.Operator):
    bl_idname = "mz.register_bilingual_translator"
    bl_label = "Register Bilingual Translation (Auto Restart)"
    bl_description = trs.pgettext_tip("Data required for bilingual translation registration")
    bl_options = {"REGISTER", "UNDO"}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Blender Will Restart")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            BilingualTranslatorData().initialize()
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Bilingual Translation Registered")
        if not bpy.app.background:
            bpy.ops.mz.restart_saved_blender()
        return {"FINISHED"}


class MZ_OT_GenerateBilingualTranslator(bpy.types.Operator):
    bl_idname = "mz.generate_bilingual_translator"
    bl_label = "Generate Bilingual Translation"
    bl_description = trs.pgettext_tip("Generate Bilingual Translation")
    bl_options = {"REGISTER"}

    swap_mo_file: bpy.props.BoolProperty(
        name="swap_mo_file",
        default=True,
        description="Exchange the compiled files with the specified language files, which can resolve UI language display issues for some plugins.",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(
            self,
            "swap_mo_file",
            text="Override the original language",
        )

    def merge_txt(self, txt, append_txt, swap):
        """生成双语翻译"""
        if txt == append_txt:
            return txt

        if swap:
            txt, append_txt = append_txt, txt
        append_txt = _APPENDED_FORMAT.sub("[＊]", append_txt)
        return f"{txt}{self.custom_delimiter}{append_txt}"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        view = context.preferences.view
        original_language = view.language
        try:
            return self.generate(context)
        except (OSError, TypeError, ValueError) as error:
            view.language = original_language
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

    def generate(self, context):
        BTD = BilingualTranslatorData()
        _, bili_mo_file = BTD.get_bilingual_mo_path()
        language_code_file, _ = BTD.get_used_language_code()
        addon_prefs = context.preferences.addons[__package__].preferences
        language_code = LANGUAGE_CODES.get(addon_prefs.bilingual_lang, "en_US")
        locale_folder, source_mo = BTD.source_catalog(language_code)
        if not BTD.get_bilingual_init_state():
            raise ValueError("Initialize bilingual translation and restart Blender before generating it.")
        BTD.ensure_stock_catalog(locale_folder, source_mo)
        BTD.refresh_aliases()
        if self.swap_mo_file and language_code not in bpy.app.translations.locales:
            raise ValueError("Restart Blender to load the updated language list, then retry Override Original Language.")
        translation_data = polib.mofile(str(source_mo), wrapwidth=180)
        context.preferences.view.language = "en_US"
        whitelist_file = BTD.get_whitelist_path()
        blacklist_file = BTD.get_blacklist_path()

        self.custom_delimiter = addon_prefs.custom_delimiter
        is_translation_preceding = int(addon_prefs.is_translation_preceding[0])
        translation_section_all = addon_prefs.translation_section_all
        selected_areas = {
            area for area, enabled in (
                ("topbar", addon_prefs.translation_section_topbar),
                ("nodes", addon_prefs.translation_section_node),
                ("node_properties", addon_prefs.translation_section_node_property),
                ("properties", addon_prefs.translation_section_properties),
                ("modifiers", addon_prefs.translation_section_modifier),
            ) if enabled
        }
        translation_section_whitelist = addon_prefs.translation_section_whitelist
        translation_section_blacklist = addon_prefs.translation_section_blacklist

        # Blender resolves a translation by context and source text globally.
        available = {key(entry.msgctxt, entry.msgid) for entry in translation_data}
        optional_node_labels = {}
        if translation_section_all or "nodes" in selected_areas:
            optional_node_labels = optional_node_menu_translations(bpy.types, language_code)
            for (label_context, label), translated in optional_node_labels.items():
                if (label_context, label) not in available:
                    translation_data.append(polib.POEntry(
                        msgid=label, msgstr=translated,
                        msgctxt=None if label_context == "*" else label_context,
                    ))
                    available.add((label_context, label))
        if translation_section_all:
            selected_keys = available
        else:
            whitelist = read_terms(whitelist_file) if translation_section_whitelist else ((), ())
            sections = collect_area_keys(bpy.types, bpy.app.version) if selected_areas else {}
            if selected_areas & {"topbar", "nodes", "properties", "modifiers"}:
                # Only Blender's shipped UI files, never scripts from the .blend.
                import bl_ui
                root = Path(bl_ui.__file__).parent
                for section, item in collect_menu_items(root, bpy.types, bpy.ops, trs.contexts):
                    if section.startswith("node_menu_"):
                        if "nodes" in selected_areas:
                            sections[section].add(item)
                            sections["nodes"].add(item)
                    elif section.startswith("modifier_menu_"):
                        if selected_areas & {"modifiers", "properties"}:
                            sections[section].add(item)
                            sections["modifiers"].add(item)
                    elif section in selected_areas or section == "modifiers" and "properties" in selected_areas:
                        sections[section].add(item)
                if selected_areas & {"modifiers", "properties"}:
                    sections["modifier_menu_deeper"].update(
                        sections["modifier_asset_keys"] - sections["modifier_menu_root"],
                    )
            if "nodes" in selected_areas:
                sections["nodes"].update(optional_node_labels)
                if ("*", "Template") in optional_node_labels:
                    sections["node_menu_root"].add(("*", "Template"))
                root_assets, deeper_assets = collect_node_asset_keys(
                    bpy.utils.system_resource("DATAFILES"), bpy.data.libraries, with_levels=True,
                )
                sections["node_menu_root"].update(root_assets)
                sections["node_menu_deeper"].update(deeper_assets)
                sections["nodes"].update(root_assets | deeper_assets)
            selected_keys = scoped_keys(available, sections, selected_areas, whitelist)
        # The same stock phrase labels the panel button and the popup title.
        selected_keys = selected_keys - {("*", "Add Modifier"), ("Operator", "Add Modifier")}
        blocked_text, blocked_keys = (
            read_terms(blacklist_file) if translation_section_blacklist else ((), ())
        )
        for entry in translation_data:
            entry_key = key(entry.msgctxt, entry.msgid)
            if entry_key in selected_keys and entry_key not in blocked_keys and entry.msgid not in blocked_text:
                entry.msgstr = self.merge_txt(
                    entry.msgstr, entry.msgid, is_translation_preceding
                )

        # Write the binary catalog synchronously on every platform, closing
        # and publishing it before selecting the locale. No external msgfmt
        # process can race Windows or outlive its temporary source directory.
        catalog = translation_data.to_binary()
        state_dir = Path(bili_mo_file).parent
        if self.swap_mo_file:
            apply_override(BTD.user_locale, state_dir, locale_folder, catalog)
            catalog = source_mo.read_bytes()
        else:
            restore_override(BTD.user_locale, state_dir)
        atomic_write(bili_mo_file, "wb", lambda handle: handle.write(catalog))
        atomic_write(language_code_file, "w", lambda handle: handle.write(language_code))
        addon_prefs.bilingual_lang_code_current = language_code
        register_ui_translations(language_code)
        context.preferences.view.language = language_code if self.swap_mo_file else BTD.locale_name
        code_idx = next((int(index) + 2 for index, code in LANGUAGE_CODES.items() if code == language_code), None)
        slot = str(code_idx) if self.swap_mo_file and code_idx is not None else "1"
        if slot not in (addon_prefs.switch_lang_slot2, addon_prefs.switch_lang_slot3):
            addon_prefs.switch_lang_slot2 = slot
        context.preferences.view.use_translate_new_dataname = False
        self.report({"INFO"}, "Bilingual Translation Generated")
        return {"FINISHED"}


class MZ_OT_DeleteBilingualTranslator(bpy.types.Operator):
    bl_idname = "mz.delete_bilingual_translator"
    bl_label = "Delete Bilingual Translation"
    bl_description = trs.pgettext_tip("Delete Bilingual Translation")
    bl_options = {"REGISTER"}

    clear_user_config: bpy.props.BoolProperty(
        name="Reset Toolkit translation settings",
        default=False,
        description="Reset language, separator, order, areas, and switch slots. Keep list files and other add-ons' translations.",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Blender Will Restart")
        layout.prop(
            self,
            "clear_user_config",
            text="Reset Toolkit translation settings",
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        view = context.preferences.view
        original_language = view.language
        if original_language == "bilingual":
            view.language = "en_US"
        try:
            BilingualTranslatorData().remove_generated_locale()
        except (OSError, ValueError, KeyError) as error:
            if original_language == "bilingual":
                view.language = original_language
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        addon_prefs = context.preferences.addons[__package__].preferences
        addon_prefs.bilingual_lang_code_current = ""
        register_ui_translations("")
        if self.clear_user_config:
            for name in (
                "bilingual_lang", "custom_delimiter", "is_translation_preceding",
                "translation_section_all", "translation_section_topbar",
                "translation_section_node", "translation_section_node_property",
                "translation_section_properties", "translation_section_modifier",
                "translation_section_whitelist", "translation_section_blacklist",
                "switch_lang_slot1", "switch_lang_slot2", "switch_lang_slot3",
            ):
                addon_prefs.property_unset(name)
        else:
            if addon_prefs.switch_lang_slot2 == "1":
                addon_prefs.switch_lang_slot2 = str(CHINESE_ID + 2)
            if addon_prefs.switch_lang_slot3 == "1":
                addon_prefs.switch_lang_slot3 = "0"
        self.report({"INFO"}, "Bilingual Translation Deleted")
        if not bpy.app.background:
            bpy.ops.mz.restart_saved_blender()
        return {"FINISHED"}


class MZ_OT_OpenBilingualBlackWhiteList(bpy.types.Operator):
    bl_idname = "mz.open_bilingual_black_white_list"
    bl_label = "Open Bilingual Translation Blacklist/Whitelist"
    bl_description = trs.pgettext_tip("Edit black/whitelist")
    bl_options = {"REGISTER", "UNDO"}

    list_type: bpy.props.BoolProperty(
        name="list_type",
        default=True,
        description="True: Whitelist, False: Blacklist",
    )  # type: ignore

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        BTD = BilingualTranslatorData()
        whitelist_file = BTD.get_whitelist_path()
        blacklist_file = BTD.get_blacklist_path()
        list_file = whitelist_file if self.list_type else blacklist_file
        list_name = os.path.basename(list_file)
        for text in bpy.data.texts:
            if text.filepath == list_file:
                self.report({"INFO"}, trs.pgettext("See '%s' in the text editor") % list_name)
                return {"FINISHED"}
        text = bpy.data.texts.load(list_file)

        self.report({"INFO"}, trs.pgettext("See '%s' in the text editor") % list_name)
        return {"FINISHED"}
