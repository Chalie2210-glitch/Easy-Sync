# -*- coding: utf-8 -*-
"""탐색기 우클릭 메뉴 등록.

파일 탐색기에서 오디오 파일을 골라 우클릭하면 "Easy Sync 로 보내기" 가
뜨게 한다.

레지스트리는 ``HKEY_CURRENT_USER`` 아래에만 쓴다. HKEY_CLASSES_ROOT 나
HKEY_LOCAL_MACHINE 은 관리자 권한이 필요하고 시스템 전체에 영향을 준다.
HKCU 는 권한도 필요 없고 지우기도 쉽다.

COM IExecuteCommand가 선택 목록 전체를 한 번에 받는다. 파일별 실행과
레거시 메뉴의 선택 개수 제한을 피하고, 경로 목록은 임시 파일로 전달한다.
"""
from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

MENU_LABEL = "Easy Sync 로 보내기"
KEY_NAME = "EasySync.Import"
SHELL_CLSID = "{94C31A68-063E-4EF3-B0E9-8D15B7794E2A}"
SHELL_CLASS_KEY = rf"Software\Classes\CLSID\{SHELL_CLSID}"
SHELL_CONFIG_KEY = r"Software\EasySync\ShellImport"

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
    # Ctrl+A may include REAPER projects or other non-audio files. Keep the
    # common verb available; the application imports supported audio only.
    yield "혼합 파일 선택", rf"Software\Classes\*\shell\{KEY_NAME}"


def shell_host_path() -> Path:
    if getattr(sys, "frozen", False):
        folder = Path(sys._MEIPASS)
    else:
        folder = Path(__file__).resolve().parent.parent / "build" / "shell"
    name = (folder / "easysync-shell-host.txt").read_text(encoding="ascii").strip()
    if Path(name).name != name or not name.startswith("EasySyncShell-") or not name.endswith(".dll"):
        raise ValueError("잘못된 탐색기 메뉴 모듈 이름입니다.")
    return folder / name


def _register_command_server() -> None:
    try:
        host = shell_host_path()
    except FileNotFoundError:
        raise RuntimeError("탐색기 메뉴 모듈이 없습니다. 설치본을 복구하거나 "
                           "소스 실행 시 packaging/build-shell.ps1을 먼저 실행하세요.") from None
    if not host.is_file():
        raise RuntimeError("탐색기 명령 실행 파일이 없습니다. 설치본을 복구하거나 "
                           "소스 실행 시 packaging/build-shell.ps1을 먼저 실행하세요.")
    exe, script = _launcher_parts()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SHELL_CONFIG_KEY) as key:
        winreg.SetValueEx(key, "Program", 0, winreg.REG_SZ, str(exe))
        winreg.SetValueEx(key, "Script", 0, winreg.REG_SZ, str(script) if script else "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SHELL_CLASS_KEY) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "Easy Sync selection command")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SHELL_CLASS_KEY + r"\InprocServer32") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(host))
        winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Apartment")


def _notify_shell() -> None:
    import ctypes
    # Wait for the Shell to receive the association-change notification.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)


def verify_installation() -> None:
    """Check this installation's registry and COM activation without launching UI."""
    import ctypes
    import uuid

    host = shell_host_path()
    exe, script = _launcher_parts()
    for file in (host, exe, script):
        if file is not None and not file.is_file():
            raise RuntimeError(f"탐색기 메뉴에 필요한 파일이 없습니다: {file}")

    def expect(key_path: str, name: str | None, expected: str) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            actual = winreg.QueryValueEx(key, name)[0]
        if actual != expected:
            raise RuntimeError("탐색기 메뉴가 다른 설치 위치를 가리킵니다. 메뉴를 다시 등록하세요.")

    expect(SHELL_CONFIG_KEY, "Program", str(exe))
    expect(SHELL_CONFIG_KEY, "Script", str(script) if script else "")
    expect(SHELL_CLASS_KEY + r"\InprocServer32", None, str(host))
    expect(SHELL_CLASS_KEY + r"\InprocServer32", "ThreadingModel", "Apartment")
    for _, base in _registration_bases():
        expect(base, "MultiSelectModel", "Player")
        expect(base + r"\command", None, _launch_command())
        expect(base + r"\command", "DelegateExecute", SHELL_CLSID)

    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    # Qt may already have initialized this thread with another COM apartment.
    if initialized < 0 and (initialized & 0xffffffff) != 0x80010106:
        raise RuntimeError(f"COM 초기화 실패: 0x{initialized & 0xffffffff:08X}")
    obj = ctypes.c_void_p()
    try:
        clsid = ctypes.create_string_buffer(uuid.UUID(SHELL_CLSID).bytes_le)
        iid = ctypes.create_string_buffer(uuid.UUID("7F9185B0-CB92-43C5-80A9-92277A4F7B54").bytes_le)
        result = ole.CoCreateInstance(clsid, None, 1, iid, ctypes.byref(obj))
        if result < 0:
            raise RuntimeError(f"탐색기 메뉴 모듈을 불러오지 못했습니다: 0x{result & 0xffffffff:08X}")
    finally:
        if obj:
            table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(obj)
        if initialized >= 0:
            ole.CoUninitialize()


def install() -> list[str]:
    """등록하고 어떤 확장자에 걸었는지 돌려준다."""
    command = _launch_command()
    _register_command_server()
    done: list[str] = []
    for ext, base in _registration_bases():
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, MENU_LABEL)
                # 아이콘은 실행 파일에서 가져온다.
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ,
                                  command.split('"')[1])
                # COM Player verbs receive the full selection, without the
                # legacy per-file invocation/100-item selection limit.
                winreg.SetValueEx(key, "MultiSelectModel", 0,
                                  winreg.REG_SZ, "Player")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  base + r"\command") as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
                winreg.SetValueEx(key, "DelegateExecute", 0, winreg.REG_SZ, SHELL_CLSID)
            done.append(ext)
        except OSError as exc:
            log.warning("%s 등록 실패: %s", ext, exc)
    _notify_shell()
    if len(done) != len(list(_registration_bases())):
        raise RuntimeError("일부 탐색기 메뉴를 등록하지 못했습니다. 메뉴를 다시 등록하세요.")
    verify_installation()
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
    for key in (SHELL_CLASS_KEY + r"\InprocServer32", SHELL_CLASS_KEY, SHELL_CONFIG_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass
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
    import os
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
        powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows"))
                      / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script_text],
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
