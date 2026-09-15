# -*- coding: utf-8 -*-
"""Wwise Command Add-on 등록.

Wwise 프로젝트 익스플로러에서 우클릭하면 Easy Sync 가 뜨게 한다.
등록 파일은 ``%APPDATA%\\Audiokinetic\\Wwise\\Add-ons\\Commands`` 에 놓는다
(사용자 범위). ``--project`` 로 프로젝트 폴더에 넣으면 팀이 공유한다.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger(__name__)

COMMAND_ID = "io.github.Chalie2210_glitch.easysync.import"
DISPLAY_NAME = "Easy Sync: 오디오 임포트..."
MENU_PATH = "Easy Sync"
ADDON_FILENAME = "easy_sync.json"

#: 우클릭 메뉴를 띄울 오브젝트 타입.
#: 2023 의 ActorMixer 와 2025 의 PropertyContainer 를 둘 다 넣는다.
CONTEXT_TYPES = (
    "Sound,PropertyContainer,ActorMixer,RandomSequenceContainer,"
    "SwitchContainer,BlendContainer,WorkUnit,Folder,Event"
)


@dataclass
class Launcher:
    program: str
    args: str
    cwd: str


def tool_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def current_launcher() -> Launcher:
    """지금 실행 중인 형태에 맞는 실행 명령을 만든다."""
    root = tool_root()
    if getattr(sys, "frozen", False):
        return Launcher(program=str(Path(sys.executable)), args="", cwd=str(root))
    # 개발 중에는 venv 의 pythonw 로 .pyw 런처를 부른다.
    # python.exe 가 아니라 pythonw.exe 여야 콘솔 창이 깜빡이지 않는다.
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = root / "run_easysync.pyw"
    # 경로에 공백이 있다("Easy Sync"). 반드시 따옴표로 감싼다.
    return Launcher(program=str(pythonw), args=f'"{launcher}"', cwd=str(root))


def build(launcher: Launcher) -> dict:
    return {
        "version": 1,
        "commands": [{
            "id": COMMAND_ID,
            "displayName": DISPLAY_NAME,
            "program": launcher.program,
            "args": launcher.args,
            # 선택이 몇 개든 프로세스를 하나만 띄운다. 선택 자체는 툴이
            # WAAPI 로 직접 읽으므로 인자 치환에 기대지 않는다 — Wwise 버전이
            # 바뀌어도 동작한다.
            # Do not reserve a default shortcut: backtick conflicts with Wwise's
            # Toggle Maximize Object Tab Primary View. Users may assign their own.
            "startMode": "MultipleSelectionSingleProcessSpaceSeparated",
            "cwd": launcher.cwd,
            # true 로 두면 Wwise 가 프로세스가 끝날 때까지 출력을 모으느라
            # 기다린다. 창을 켜 두는 내내 Wwise 가 멈춘다.
            "redirectOutputs": False,
            "contextMenu": {"basePath": MENU_PATH, "enabledFor": CONTEXT_TYPES},
            "mainMenu": {"basePath": MENU_PATH},
        }, {
            "id": "io.github.Chalie2210_glitch.easysync.revealSource",
            "displayName": "가져온 원본 파일 찾기",
            "program": launcher.program,
            "args": launcher.args + " --reveal-source ${id}",
            "startMode": "MultipleSelectionSingleProcessSpaceSeparated",
            "cwd": launcher.cwd,
            "redirectOutputs": False,
            "contextMenu": {"basePath": MENU_PATH,
                            "enabledFor": "Sound,AudioFileSource"},
        }],
    }


def user_commands_dir() -> Path:
    import os
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "Audiokinetic" / "Wwise" / "Add-ons" / "Commands"


def project_commands_dir() -> Path | None:
    """프로젝트의 Add-ons/Commands 폴더. 팀 공유용."""
    try:
        from .waapi_bridge import WwiseBridge
        with WwiseBridge() as client:
            info = client._call("ak.wwise.core.getProjectInfo") or {}
        commands = (info.get("directories") or {}).get("commands")
        return Path(commands) if commands else None
    except Exception as exc:  # noqa: BLE001
        log.warning("프로젝트 폴더를 찾지 못했습니다: %s", exc)
        return None


def reload_addons() -> bool:
    """Wwise 에 애드온을 다시 읽으라고 시킨다. 재시작이 필요 없다."""
    try:
        from .waapi_bridge import WwiseBridge
        with WwiseBridge() as client:
            client._call("ak.wwise.ui.commands.execute",
                        {"command": "ReloadCommandAddons"})
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("애드온 새로고침 실패: %s", exc)
        return False


def install(launcher: Launcher | None = None, *, project: bool = False) -> Path:
    target_dir = project_commands_dir() if project else user_commands_dir()
    if target_dir is None:
        raise RuntimeError("프로젝트 Add-ons 폴더를 찾지 못했습니다. "
                           "Wwise 가 실행 중인지 확인하세요.")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / ADDON_FILENAME
    payload = build(launcher or current_launcher())
    path.write_text(json.dumps(payload, indent=4, ensure_ascii=False),
                    encoding="utf-8")
    return path


def uninstall(*, project: bool = False) -> Path | None:
    target_dir = project_commands_dir() if project else user_commands_dir()
    if target_dir is None:
        return None
    path = target_dir / ADDON_FILENAME
    if path.exists():
        path.unlink()
        return path
    return None


def installed_program() -> str | None:
    """지금 등록되어 있는 실행 파일 경로. 없으면 None."""
    path = user_commands_dir() / ADDON_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["commands"][0]["program"]
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return None


def cli_install() -> int:
    path = install()
    print(f"Wwise 애드온을 등록했습니다: {path}")
    if reload_addons():
        print("Wwise 가 애드온을 다시 읽었습니다. 바로 쓸 수 있습니다.")
    else:
        print("Wwise 를 다시 시작하면 메뉴에 나타납니다.")
    return 0


def cli_uninstall() -> int:
    path = uninstall()
    print(f"등록을 해제했습니다: {path}" if path else "등록된 애드온이 없습니다.")
    reload_addons()
    return 0
