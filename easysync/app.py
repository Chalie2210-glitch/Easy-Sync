# -*- coding: utf-8 -*-
"""Easy Sync 진입점."""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import addon, shellmenu, single_instance
from .settings import Settings
from .link import WwiseLink
from .waapi_bridge import WwiseBridge, WwiseUnavailable

APP_NAME = "Easy Sync"
AUDIO_SUFFIXES = {".wav", ".aif", ".aiff", ".flac", ".ogg"}


def _tool_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _writable_dir(preferred: Path) -> Path:
    """쓸 수 있는 폴더를 고른다.

    툴이 읽기 전용 위치(네트워크 드라이브, Program Files)에 놓일 수 있다.
    그때 로그를 못 써서 툴이 아예 뜨지 않으면 안 된다.
    """
    probe = preferred / ".easysync_write_test"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return preferred
    except OSError:
        fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EasySync"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            return Path(os.environ.get("TEMP", "."))


TOOL_ROOT = _tool_root()
DATA_ROOT = _writable_dir(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EasySync" / "Logs")
LOG_PATH = DATA_ROOT / "easysync.log"


def _setup_logging(verbose: bool) -> None:
    """로그를 파일로 남긴다.

    pythonw.exe 로 실행되면 콘솔이 없고 ``sys.stderr`` 가 ``None`` 이다.
    거기에 StreamHandler 를 붙이면 로그를 남길 때마다 예외가 난다.
    """
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


#: 기본 글자 크기(포인트). Qt 기본값 9pt 보다 조금 크게.
FONT_POINT_SIZE = 10

#: 트리 선택색. Qt 기본 파란색은 어느 항목이 임포트 대상인지 알려 주지
#: 못하고 포커스만 표시한다. 초록 계열로 바꿔 "고른 것" 을 뜻하게 한다.
_STYLE = """
QTreeWidget::item { padding: 3px 2px; }
QTreeWidget::item:selected {
    background: #2f6b46;
    color: #f0f6f2;
}
QTreeWidget::item:selected:!active {
    background: #2a5a3c;
    color: #e2ece6;
}
QGroupBox { margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
"""


def _apply_style(app: QApplication) -> None:
    font = app.font()
    font.setPointSize(FONT_POINT_SIZE)
    app.setFont(font)
    app.setStyleSheet(_STYLE)


def _fail(server, title: str, message: str) -> None:
    """시작에 실패했을 때 알리고 **반드시 포트를 놓는다**.

    포트를 쥔 채로 남으면 그 다음부터 우클릭이 전부 무시된다. 실제로 겪은
    사고라 실패 경로마다 여기를 지나게 했다.
    """
    if server is not None:
        try:
            server.close()
        except Exception:  # noqa: BLE001
            pass
    logging.getLogger(__name__).error("%s: %s", title, message)
    QMessageBox.critical(None, title, message)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="easysync", description=APP_NAME)
    parser.add_argument("files", nargs="*",
                        help="임포트할 오디오 파일. 탐색기 우클릭으로 넘어온다.")
    parser.add_argument("--waapi-url", default=None, help="WAAPI 주소 재정의")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--install-addon", action="store_true",
                        help="Wwise 우클릭 메뉴에 등록")
    parser.add_argument("--uninstall-addon", action="store_true")
    parser.add_argument("--install-shell", action="store_true",
                        help="탐색기 우클릭 메뉴에 등록")
    parser.add_argument("--uninstall-shell", action="store_true")
    parser.add_argument("--reveal-source", nargs="*", default=None,
                        help="Wwise 오브젝트 GUID의 최초 임포트 원본 찾기")
    parser.add_argument("--self-test", action="store_true",
                        help="Wwise 연결만 확인하고 끝낸다")
    return parser.parse_args(argv)


def _collect_files(raw: list[str]) -> list[Path]:
    """인자로 받은 경로에서 오디오 파일만 추린다.

    탐색기에서 여러 파일을 골라 우클릭하면 경로가 그대로 인자로 들어온다.
    폴더가 섞여 들어오면 그 안의 오디오까지 훑는다.
    """
    out: list[Path] = []
    for item in raw:
        path = Path(item)
        if path.is_dir():
            out.extend(p for p in sorted(path.rglob("*"))
                       if p.suffix.lower() in AUDIO_SUFFIXES)
        elif path.suffix.lower() in AUDIO_SUFFIXES and path.exists():
            out.append(path)
    return out


_UNCLAIMED = object()


def main(argv: list[str] | None = None, *, preclaimed_server=_UNCLAIMED) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    _setup_logging(args.verbose)
    log = logging.getLogger(__name__)
    log.info("%s 시작", APP_NAME)

    # 등록/해제는 창을 띄우지 않는다.
    if args.install_addon:
        return addon.cli_install()
    if args.uninstall_addon:
        return addon.cli_uninstall()
    if args.install_shell:
        return shellmenu.cli_install()
    if args.uninstall_shell:
        return shellmenu.cli_uninstall()

    if args.reveal_source is not None:
        from .source_location import run
        return run(args.reveal_source, args.waapi_url)

    files = [Path(p).absolute() for p in args.files]

    # 탐색기는 고른 파일 개수만큼 이 프로그램을 띄운다. 창 하나로 모은다.
    # 넘기기가 실패하면 종료하지 않고 내 창을 연다 — 모으기에 실패하는 것과
    # 아예 안 켜지는 것은 전혀 다른 문제다. 자세한 이유는 single_instance
    # 모듈 주석 참고.
    server = (single_instance.claim() if preclaimed_server is _UNCLAIMED
              else preclaimed_server)
    if server is None:
        if preclaimed_server is _UNCLAIMED and single_instance.forward(files):
            log.info("이미 떠 있는 창에 파일 %d개를 넘기고 종료", len(files))
            return 0
        log.warning("포트는 잡혀 있으나 응답이 없습니다. 창을 따로 엽니다.")

    app = QApplication(sys.argv[:1])
    # An installer must wait until the application has finished all imports.
    import ctypes
    from .version import APP_MUTEX, VERSION
    ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
    app._install_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    _apply_style(app)

    # --self-test 만 Wwise 를 바로 요구한다. 평소에는 창을 먼저 띄운다.
    if args.self_test:
        try:
            with WwiseBridge(args.waapi_url) as bridge:
                info = bridge.project_info()
                QMessageBox.information(
                    None, f"{APP_NAME} - 연결 확인",
                    f"프로젝트: {info.name}\n"
                    f"{info.version}\n"
                    f"전송: {bridge.transport_name}\n"
                    f"오디오 루트: {info.roots.containers}\n"
                    f"이벤트 루트: {info.roots.events}\n"
                    f"Originals: {info.originals_root}")
            return 0
        except WwiseUnavailable as exc:
            _fail(server, f"{APP_NAME} - Wwise 연결 실패", str(exc))
            return 2

    # Wwise 가 없어도 창은 뜬다. 연결은 뒤에서 계속 시도하고, Wwise 를 켜면
    # 몇 초 안에 스스로 붙는다. 쓰던 중에 Wwise 가 꺼져도 같은 방식으로
    # 기다렸다가 다시 붙는다.
    link = WwiseLink(args.waapi_url)
    try:
        from .ui import MainWindow  # 창을 띄울 때만 불러온다

        window = MainWindow(link, Settings.load(), [])
        window.show()

        # 형제 프로세스가 늦게 보내는 파일을 창에 더한다. 소켓 스레드에서
        # 위젯을 직접 건드리면 안 되므로 시그널로 UI 스레드에 넘긴다.
        # 창이 실제로 뜬 뒤에야 응답하도록 ready 를 여기서 세운다.
        if server is not None:
            ready = threading.Event()
            single_instance.serve(server, window.files_received.emit, ready)
            ready.set()

        QTimer.singleShot(0, link.start)
        if files:
            QTimer.singleShot(0, lambda: window._on_files_received(files))
        return app.exec()
    except Exception as exc:  # noqa: BLE001
        _fail(server, f"{APP_NAME} - 시작 실패",
              f"창을 여는 중 문제가 생겼습니다.\n\n{exc}\n\n자세한 내용: {LOG_PATH}")
        log.exception("창 생성 실패")
        return 2
    finally:
        link.stop()
