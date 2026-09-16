# -*- coding: utf-8 -*-
"""Easy Sync 런처.

Wwise 애드온과 탐색기 우클릭 메뉴가 이 파일을 부른다.
``.pyw`` 확장자와 pythonw.exe 조합이라 콘솔 창이 깜빡이지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

def launch(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        from easysync.version import VERSION
        if sys.stdout is not None:
            print(VERSION)
        return 0
    if args[:1] == ["--register-integration"] and len(args) == 2:
        from easysync.integration import install
        install(args[1])
        return 0
    if args == ["--unregister-integration"]:
        from easysync.integration import uninstall
        uninstall()
        return 0
    if args[:1] == ["--smoke-test"] and len(args) == 2:
        import json
        from PySide6.QtWidgets import QApplication
        from easysync.ui import MainWindow
        from easysync.link import WwiseLink
        from easysync.settings import Settings
        from easysync.version import VERSION
        from waapi import WaapiClient  # Verify the optional WAMP transport is bundled.
        app = QApplication([])
        window = MainWindow(WwiseLink(), Settings(), [])
        window._persist = lambda: None
        window.show()
        app.processEvents()
        Path(args[1]).write_text(json.dumps({"version": VERSION, "visible": window.isVisible()}), encoding="utf-8")
        window.close()
        return 0
    # Claim/forward before importing Qt or WAAPI. Explorer may invoke this once
    # per selected file; only the owner needs the expensive GUI imports.
    if not any(arg.startswith("-") for arg in args):
        from easysync import single_instance
        try:
            server = single_instance.acquire([Path(p).absolute() for p in args])
        except single_instance.InstanceUnavailable as exc:
            single_instance.report_unavailable(exc)
            return 2
        if server is None:
            return 0
        try:
            from easysync.app import main
            return main(args, preclaimed_server=server)
        finally:
            if server is not None:
                server.close()
    from easysync.app import main
    return main(args)


if __name__ == "__main__":
    if sys.argv[1:2] == ['--smoke-test']:
        # A windowed executable otherwise opens a blocking traceback dialog in CI.
        try:
            result = launch()
        except Exception:
            import json
            import traceback
            Path(sys.argv[2]).write_text(json.dumps({'error': traceback.format_exc()}), encoding='utf-8')
            result = 1
        sys.exit(result)
    sys.exit(launch())
