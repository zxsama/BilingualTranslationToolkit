import os
from pathlib import Path
import shutil
import sys
import bpy
import subprocess
from bpy.types import bpy_prop_collection
from .cross_version_support import VersionPlatformManager as VP_Manager

def collection_search(ID):
    def users(col):
        ret = tuple(repr(o) for o in col if o.user_of_id(ID))
        return ret if ret else None

    return filter(
        None,
        (
            users(getattr(bpy.data, p))
            for p in dir(bpy.data)
            if isinstance(getattr(bpy.data, p, None), bpy_prop_collection)
        ),
    )


def _windows_steam_executable(blender_path):
    import winreg

    key_name = r"Software\Valve\Steam"
    for hive, name, view in (
        (winreg.HKEY_CURRENT_USER, "SteamExe", 0),
        (winreg.HKEY_LOCAL_MACHINE, "InstallPath", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, "InstallPath", winreg.KEY_WOW64_64KEY),
    ):
        try:
            with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value:
            path = Path(os.path.expandvars(value))
            if name == "InstallPath":
                path /= "steam.exe"
            if path.is_absolute() and path.is_file():
                return str(path)

    # A secondary Steam library may not contain steam.exe; the registry above
    # resolves the client independently of where Blender is installed.
    for directory in Path(blender_path).parents:
        if directory.name.lower() == "steamapps":
            candidate = directory.parent / "steam.exe"
            if candidate.is_file():
                return str(candidate)
            break
    candidate = shutil.which("steam.exe")
    if candidate:
        return os.path.abspath(candidate)
    raise FileNotFoundError("Steam executable not found. Restart Blender from Steam.")


def launch_blender(
    file_path: str = "", steam_app_id: str = "365670", is_admin: bool = False
):
    """
    启动Blender, 支持steam与常规安装, 支持管理员启动
    """

    # get blender.exe path
    blender_exe = bpy.app.binary_path

    # launch
    if any(part.lower() == "steamapps" for part in Path(blender_exe).parts):
        # steam安装
        steam = _windows_steam_executable(blender_exe) if sys.platform == "win32" else "steam"
        command = [steam, "-applaunch", steam_app_id]
        if file_path:
            command.append(file_path)
        subprocess.Popen(command)
    else:
        # 常规安装
        parameter = [file_path] if file_path else []
        VPM = VP_Manager()
        VPM.run_command(is_admin, parameter, program_path=blender_exe)
