# -*- coding: utf-8 -*-
"""실행 중인 Wwise 개수 세기.

Easy Sync 는 **켜져 있는 Wwise 에 붙는다.** 어느 프로젝트를 쓸지 설정으로
고정하지 않는다 — 사운드 작업은 프로젝트를 자주 바꾸는데 그때마다 툴 설정을
고치게 하면 번거롭기만 하다.

문제는 Wwise 를 두 개 이상 켜 놓았을 때다. WAAPI 포트(8080/8090)는 먼저 뜬
쪽이 가져가므로, 사용자가 보고 있는 창과 Easy Sync 가 말하고 있는 창이 다를
수 있다. 조용히 엉뚱한 프로젝트에 임포트하는 것이 최악이라 **몇 개가 떠 있는지
세어 알려 준다.**

프로세스 목록은 ``tasklist`` 로 읽는다. 자주 부르는 것이 아니고(붙을 때 한 번)
추가 의존성이 없는 쪽이 낫다.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

WWISE_IMAGE = "Wwise.exe"
#: 프로세스 목록을 기다리는 최대 시간(초).
TIMEOUT = 5.0
#: 콘솔 창이 깜빡이지 않게 한다. pythonw 로 실행돼도 tasklist 는 창을 연다.
_NO_WINDOW = 0x08000000


def count_wwise() -> int:
    """실행 중인 Wwise 개수. 셀 수 없으면 -1.

    -1 과 0 을 구분한다 — "없다" 와 "모르겠다" 는 다르다. 모르는 상태에서
    경고를 띄우면 쓸데없이 불안하게 만든다.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {WWISE_IMAGE}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=TIMEOUT,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Wwise 프로세스를 세지 못했습니다: %s", exc)
        return -1

    count = 0
    for line in result.stdout.splitlines():
        # CSV 형식이라 이미지 이름이 첫 칸에 따옴표로 온다.
        # 조건에 맞는 것이 없으면 tasklist 가 안내 문구를 내므로 그건 세지 않는다.
        if line.strip().lower().startswith(f'"{WWISE_IMAGE.lower()}"'):
            count += 1
    return count


def duplicate_warning(project_name: str) -> str:
    """Wwise 가 여러 개면 경고 문구, 아니면 빈 문자열."""
    running = count_wwise()
    if running <= 1:
        return ""
    return (f"Wwise 가 {running}개 실행 중입니다. "
            f"Easy Sync 는 '{project_name}' 에 연결되어 있습니다 — "
            f"보고 계신 창과 다를 수 있습니다.")
