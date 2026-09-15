"""Installer entry points. No Qt/UI imports required."""
import json
from pathlib import Path

from . import addon, shellmenu


def install(kind: str) -> None:
    if kind == "wwise":
        addon.install()
        addon.reload_addons()
    elif kind == "shell":
        if len(shellmenu.install()) != len(shellmenu.EXTENSIONS) + 1:
            raise RuntimeError("일부 탐색기 메뉴를 등록하지 못했습니다.")
        if shellmenu.install_sendto() is None:
            raise RuntimeError("보내기 바로가기를 만들지 못했습니다.")
    else:
        raise ValueError(kind)


def uninstall() -> None:
    # Another installation may own the current menu; do not remove its entries.
    launcher = addon.current_launcher()
    path = addon.user_commands_dir() / addon.ADDON_FILENAME
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = data.get("commands", [])
        keep = [c for c in commands if Path(c.get("program", "")) != Path(launcher.program)]
        if len(keep) != len(commands):
            if keep:
                data["commands"] = keep
                path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            else:
                path.unlink()
            addon.reload_addons()
    if shellmenu.installed_command() == shellmenu._launch_command():
        shellmenu.uninstall()
        shellmenu.uninstall_sendto()
