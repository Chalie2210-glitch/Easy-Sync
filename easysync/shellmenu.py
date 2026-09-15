# -*- coding: utf-8 -*-
"""탐색기 우클릭 메뉴 등록.

파일 탐색기에서 오디오 파일을 골라 우클릭하면 "Easy Sync 로 보내기" 가
뜨게 한다.

레지스트리는 ``HKEY_CURRENT_USER`` 아래에만 쓴다. HKEY_CLASSES_ROOT 나
HKEY_LOCAL_MACHINE 은 관리자 권한이 필요하고 시스템 전체에 영향을 준다.
HKCU 는 권한도 필요 없고 지우기도 쉽다.

여러 파일 선택은 MultiSelectModel=Player로 메뉴 표시를 허용한다.
레거시 정적 verb는 파일마다 %1을 전달하므로 단일 인스턴스 IPC로 합친다.
%*는 선택 파일 목록이 아니며 Explorer 호출에서는 빈 값일 수 있다.
정적 verb는 100개 선택 제한이 있다. 더 큰 묶음은 폴더 우클릭이나 보내기를 쓴다.
"""
from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

MENU_LABEL = "Easy Sync 로 보내기"
KEY_NAME = "EasySync.Import"

#: 메뉴를 붙일 확장자.
EXTENSIONS = [".wav", ".aif", ".aiff", ".flac", ".ogg"]


def _launcher_parts() -> tuple[Path, Path | None]:
    """(실행 파일, 스크립트) — 스크립트는 빌드된 exe 면 None."""
    root = Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        return Path(sys.executable), None
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw, root / "run_easysync.pyw"


def _launch_command() -> str:
    """선택한 파일을 %1로 전달한다. 여러 실행은 IPC로 합친다."""
    exe, script = _launcher_parts()
    # 경로에 공백이 있으므로 각 조각을 따옴표로 감싼다.
    if script is None:
        return f'"{exe}" "%1"'
    return f'"{exe}" "{script}" "%1"'


def _registration_bases():
    for ext in EXTENSIONS:
        yield ext, rf"Software\Classes\SystemFileAssociations\{ext}\shell\{KEY_NAME}"
    yield "폴더", rf"Software\Classes\Directory\shell\{KEY_NAME}"


def _notify_shell() -> None:
    import ctypes
    # Wait for the Shell to receive the association-change notification.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)


def install() -> list[str]:
    """등록하고 어떤 확장자에 걸었는지 돌려준다."""
    command = _launch_command()
    done: list[str] = []
    for ext, base in _registration_bases():
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, MENU_LABEL)
                # 아이콘은 실행 파일에서 가져온다.
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ,
                                  command.split('"')[1])
                # Legacy verbs otherwise disappear above 15 selected items.
                winreg.SetValueEx(key, "MultiSelectModel", 0,
                                  winreg.REG_SZ, "Player")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  base + r"\command") as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
            done.append(ext)
        except OSError as exc:
            log.warning("%s 등록 실패: %s", ext, exc)
    _notify_shell()
    return done


def uninstall() -> list[str]:
    removed: list[str] = []
    for ext, base in _registration_bases():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + r"\command")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
            removed.append(ext)
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("%s 해제 실패: %s", ext, exc)
    _notify_shell()
    return removed


SENDTO_NAME = "Easy Sync.lnk"


def sendto_path() -> Path:
    import os
    return (Path(os.environ.get("APPDATA", Path.home()))
            / "Microsoft" / "Windows" / "SendTo" / SENDTO_NAME)


def install_sendto() -> Path | None:
    """'보내기' 메뉴에 바로가기를 만든다.

    Windows 11 의 새 우클릭 메뉴는 패키지 앱이 아닌 프로그램의 등록 항목을
    바로 보여 주지 않는다 — classic 항목은 '추가 옵션 표시' 안으로 들어간다.
    '보내기' 는 한 단계 더 들어가긴 해도 위치가 일정해서 찾기 쉽다. 두 경로를
    모두 열어 두면 어느 쪽이든 쓸 수 있다.

    바로가기(.lnk) 생성에는 COM 이 필요해서 PowerShell 을 잠깐 부른다.
    pywin32 를 의존성으로 더하지 않기 위해서다.
    """
    import subprocess

    exe, script = _launcher_parts()
    link = sendto_path()
    arguments = f'"{script}"' if script is not None else ""
    workdir = str((script or exe).parent)

    script_text = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.Description = 'Easy Sync 로 보내기';"
        "$s.Save()" % tuple(str(v).replace("'", "''")
                            for v in (link, exe, arguments, workdir))
    )
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script_text],
            check=True, capture_output=True, timeout=30,
            creationflags=0x08000000)  # CREATE_NO_WINDOW
    except Exception as exc:  # noqa: BLE001
        log.warning("보내기 바로가기 생성 실패: %s", exc)
        return None
    return link if link.exists() else None


def uninstall_sendto() -> Path | None:
    link = sendto_path()
    if link.exists():
        link.unlink()
        return link
    return None


def installed_command() -> str | None:
    base = (rf"Software\Classes\SystemFileAssociations\{EXTENSIONS[0]}"
            rf"\shell\{KEY_NAME}\command")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            return winreg.QueryValueEx(key, None)[0]
    except OSError:
        return None


def cli_install() -> int:
    done = install()
    link = install_sendto()
    if done:
        print("탐색기 우클릭 메뉴에 등록했습니다: " + ", ".join(done))
        print(f"  오디오 파일 우클릭 -> '{MENU_LABEL}'")
        print("  Windows 11 에서는 '추가 옵션 표시'(Shift+F10) 안에 있습니다.")
    if link:
        print(f"보내기 메뉴에도 넣었습니다: {link}")
        print("  우클릭 -> 보내기 -> Easy Sync")
    if not done and not link:
        print("등록에 실패했습니다.")
        return 1
    return 0


def cli_uninstall() -> int:
    removed = uninstall()
    print("해제했습니다: " + ", ".join(removed) if removed
          else "등록된 항목이 없습니다.")
    link = uninstall_sendto()
    if link:
        print(f"보내기 바로가기도 지웠습니다: {link}")
    return 0
