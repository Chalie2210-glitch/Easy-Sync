# -*- coding: utf-8 -*-
"""Easy Sync 등록/해제 CLI.

    python install_addon.py              Wwise 애드온 + 탐색기 메뉴 둘 다 등록
    python install_addon.py --wwise      Wwise 우클릭 메뉴만
    python install_addon.py --shell      탐색기 우클릭 메뉴만
    python install_addon.py --project    Wwise 애드온을 프로젝트 폴더에 (팀 공유)
    python install_addon.py --uninstall  등록 해제
    python install_addon.py --print      지금 어떻게 등록되어 있는지 보기
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from easysync import addon, shellmenu  # noqa: E402


def show() -> int:
    launcher = addon.current_launcher()
    print("이번 빌드의 실행 명령")
    print(f"  program : {launcher.program}")
    print(f"  args    : {launcher.args}")
    print(f"  cwd     : {launcher.cwd}")
    print()
    registered = addon.installed_program()
    print("Wwise 애드온")
    if registered:
        state = "최신" if registered == launcher.program else "오래됨 (다시 등록하세요)"
        print(f"  등록됨: {registered}  [{state}]")
        print(f"  파일  : {addon.user_commands_dir() / addon.ADDON_FILENAME}")
    else:
        print("  등록되지 않음")
    print()
    print("탐색기 우클릭 메뉴")
    command = shellmenu.installed_command()
    print(f"  {command}" if command else "  등록되지 않음")
    print()
    print("등록될 JSON:")
    print(json.dumps(addon.build(launcher), indent=4, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Easy Sync 등록 도구")
    parser.add_argument("--wwise", action="store_true", help="Wwise 애드온만")
    parser.add_argument("--shell", action="store_true", help="탐색기 메뉴만")
    parser.add_argument("--project", action="store_true",
                        help="Wwise 애드온을 프로젝트 폴더에 등록 (팀 공유)")
    parser.add_argument("--uninstall", action="store_true", help="등록 해제")
    parser.add_argument("--print", dest="show", action="store_true",
                        help="현재 등록 상태만 출력")
    args = parser.parse_args()

    if args.show:
        return show()

    # 아무것도 고르지 않으면 둘 다.
    do_wwise = args.wwise or not (args.wwise or args.shell)
    do_shell = args.shell or not (args.wwise or args.shell)

    if args.uninstall:
        if do_wwise:
            path = addon.uninstall(project=args.project)
            print(f"Wwise 애드온 해제: {path}" if path else "Wwise 애드온: 등록된 것 없음")
            addon.reload_addons()
        if do_shell:
            removed = shellmenu.uninstall()
            print("탐색기 메뉴 해제: " + (", ".join(removed) if removed else "등록된 것 없음"))
        return 0

    if do_wwise:
        try:
            path = addon.install(project=args.project)
            print(f"Wwise 애드온 등록: {path}")
            if addon.reload_addons():
                print("  Wwise 가 애드온을 다시 읽었습니다. 재시작 없이 바로 쓸 수 있습니다.")
            else:
                print("  Wwise 를 다시 시작하면 메뉴에 나타납니다.")
        except Exception as exc:  # noqa: BLE001
            print(f"Wwise 애드온 등록 실패: {exc}")
            return 1
    if do_shell:
        done = shellmenu.install()
        if done:
            print("탐색기 우클릭 메뉴 등록: " + ", ".join(done))
            print(f"  오디오 파일을 우클릭하면 '{shellmenu.MENU_LABEL}' 이 보입니다.")
        else:
            print("탐색기 메뉴 등록 실패")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
