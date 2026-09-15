# -*- coding: utf-8 -*-
"""이름 처리 — 그룹 키 유도와 Wwise 이름 정리.

두 가지 다른 일을 한다.

``group_key`` 는 **편의** 기능이다. ``Creature_SFX_01`` 을 ``Creature_SFX`` 로
접어 같은 컨테이너 후보로 묶는다. 틀려도 사용자가 UI 에서 고치면 되므로
과감하게 추측해도 된다.

``sanitize`` 는 **안전** 기능이다. 가장 중요한 역할은 미용이 아니라 경로 주입
차단이다. 값 안에 역슬래시가 들어 있으면 계층이 하나 더 생기는 것이 아니라
반드시 한 세그먼트로 접혀야 한다. ``<`` ``>`` 는 임포트 경로의 타입 토큰
구분자라서 이름에 들어가면 엉뚱한 타입이 만들어진다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: 이름에서 금지되는 문자. 각각 이유가 다르다.
DENY_CHARS = frozenset(
    "\\/"      # 경로 구분자 — 주입 차단. 이 함수가 존재하는 이유다.
    "<>"       # 임포트 경로의 타입 토큰 구분자
    ":*?\""    # Windows 예약 문자 (Originals 폴더 이름으로도 쓰인다)
    "|'"       # WAQL 문자열 리터럴을 깨뜨린다
)

#: 뒤에 붙은 인덱스를 떼는 패턴. 위에서부터 먼저 맞는 것 하나만 적용한다.
#: ``_01`` ``-01`` `` 01`` ``_v01`` ``_take3`` 를 모두 잡는다.
_INDEX_PATTERNS = [
    re.compile(r"[ _\-]+(?:v|ver|take|tk)[ _\-]?\d+$", re.IGNORECASE),
    re.compile(r"[ _\-]+\d+$"),
]

#: 파일을 복제할 때 뒤에 붙는 꼬리표. 인덱스보다 **먼저** 떼야 한다.
#:
#: ``Creature_Die_Voice_01 - 복사본`` 처럼 인덱스 뒤에 꼬리표가 붙으면
#: 인덱스 패턴이 걸리지 않아 파일마다 그룹이 하나씩 생긴다. 실제로
#: 겪은 문제라 여기서 먼저 정리한다.
_COPY_SUFFIXES = [
    re.compile(r"[ _\-]*[-–]?[ _]*복사본(?:[ _]*\(\d+\))?$"),
    re.compile(r"[ _\-]*[-–]?[ _]*cop(?:y|ie)s?(?:[ _]*\(\d+\))?$", re.IGNORECASE),
    re.compile(r"[ _\-]*\(\d+\)$"),
]


def strip_extension(filename: str) -> str:
    """``a/b/c.wav`` -> ``c``. 경로 구분자와 확장자를 함께 떼어낸다."""
    base = re.split(r"[\\/]", filename)[-1]
    stem = re.sub(r"\.[^.]+$", "", base)
    return stem


def strip_copy_suffix(name: str) -> str:
    """``- 복사본``, ``- Copy``, ``(2)`` 같은 복제 꼬리표를 뗀다.

    여러 번 붙어 있을 수 있어(``... - 복사본 - 복사본``) 더 뗄 것이 없을
    때까지 돌린다.
    """
    out = name
    while True:
        for pattern in _COPY_SUFFIXES:
            stripped = pattern.sub("", out).strip()
            if stripped and stripped != out:
                out = stripped
                break
        else:
            return out


def object_name(filename: str) -> str:
    """Wwise 에 만들어질 오브젝트 이름.

    복제 꼬리표는 뗀다 — ``Creature_Die_Voice_01 - 복사본`` 이라는 이름의
    Sound 를 원하는 사람은 없다. 인덱스는 남긴다. 그게 개별 파일을
    구분하는 유일한 표시이기 때문이다.
    """
    stem = strip_copy_suffix(strip_extension(filename))
    return stem


def group_key(filename: str) -> str:
    """파일 이름에서 컨테이너 후보 이름을 뽑는다.

    ``Creature_SFX_01.wav`` -> ``Creature_SFX``.
    ``Creature_Die_Voice_01 - 복사본.wav`` -> ``Creature_Die_Voice``.

    뒤 인덱스가 없는 이름(예: 효과음 라이브러리에서 받은 긴 이름)은 그대로
    돌아온다. 그러면 파일 하나짜리 그룹이 되는데, 그게 맞는 동작이다 —
    묶을 근거가 없는 것을 임의로 묶으면 안 된다. 그런 경우에는 사용자가
    UI 에서 여러 그룹을 직접 합친다.
    """
    stem = object_name(filename)
    for pattern in _INDEX_PATTERNS:
        stripped = pattern.sub("", stem)
        if stripped and stripped != stem:
            return stripped
    return stem


@dataclass(frozen=True)
class SanitizeResult:
    value: str
    changed: bool
    truncated: bool


def sanitize(name: str, *, replacement: str = "_", max_length: int = 0) -> SanitizeResult:
    """Wwise 오브젝트 이름으로 안전한 문자열을 만든다.

    ``changed`` 와 ``truncated`` 를 따로 돌려주는 이유: 미리보기에서 "정리했다"
    와 "잘라냈다" 는 사용자에게 전혀 다른 의미다. 앞은 넘어가도 되지만 뒤는
    이름이 같아져 서로 덮어쓸 수 있으니 눈에 띄어야 한다.

    ``max_length`` 기본값이 0(제한 없음)인 것도 같은 이유다. 조용히 자르면
    식별자가 깨진다. 자를지는 부르는 쪽이 정한다.
    """
    chars: list[str] = []
    changed = False
    for ch in name:
        # 제어 문자도 막는다. 엑셀이나 CSV 에서 붙여넣으면 실제로 섞여 온다.
        if ch in DENY_CHARS or ord(ch) < 0x20:
            chars.append(replacement)
            changed = True
        else:
            chars.append(ch)
    value = "".join(chars).strip()
    if value != "".join(chars):
        changed = True

    truncated = False
    if max_length and len(value) > max_length:
        value = value[:max_length].rstrip()
        truncated = True

    if not value:
        # 전부 금지 문자였던 경우. 빈 이름은 Wwise 가 거부한다.
        value = "Unnamed"
        changed = True
    return SanitizeResult(value, changed, truncated)


def sanitized(name: str) -> str:
    """``sanitize`` 의 값만 필요할 때 쓰는 짧은 형태."""
    return sanitize(name).value


def default_event_name(container_name: str) -> str:
    """컨테이너 이름에서 기본 이벤트 이름을 만든다."""
    return sanitized(container_name)


def natural_key(text: str) -> list:
    """``_2`` 가 ``_10`` 보다 앞에 오도록 정렬하는 키."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def words_of(path: Path | str, *, include_parent: bool = True) -> list[str]:
    """파일에서 이름 조각을 뽑는다.

    ``Surface_Sand/Creature_Footstep_Sand_A_ACT_01.wav`` 에서
    ``['CR','NPC','SF','Sand','A','ACT','01','PM01','Sand']`` 를 얻는다.

    프로젝트마다 이름 규칙이 다르므로 ``_`` 로 쪼개는 것만 공통으로 본다.
    상위 폴더까지 보는 이유: 표면이나 상태를 폴더로 나눠 두는 경우가 흔한데
    (``Surface_Sand/``), 파일 이름에는 그 정보가 빠져 있을 수 있다.
    """
    path = Path(path)
    chunks = [strip_extension(path.name)]
    if include_parent and path.parent.name:
        chunks.append(path.parent.name)
    out: list[str] = []
    for chunk in chunks:
        out.extend(w for w in re.split(r"[ _\-.]+", chunk) if w)
    return out


def match_switch(path: Path | str, switch_names: list[str]) -> str:
    """파일 이름에서 스위치 이름을 찾아 돌려준다. 없으면 빈 문자열.

    ``Creature_Footstep_Sand_A_ACT_01.wav`` + ``["Sand","Grass",...]`` -> ``"Sand"``.

    파일 이름을 폴더 이름보다 먼저 본다. 폴더는 임시로 모아 둔 것일 수
    있지만 파일 이름은 대개 끝까지 따라다닌다.

    여러 개가 맞으면 **긴 쪽**을 고른다. ``Water`` 와 ``WaterDeep`` 이 둘 다
    있을 때 ``WaterDeep`` 파일이 ``Water`` 로 가면 안 된다.
    """
    if not switch_names:
        return ""
    by_lower = {name.lower(): name for name in switch_names}

    path = Path(path)
    # 파일 이름 먼저, 그 다음 폴더 이름.
    for chunk in (strip_extension(path.name), path.parent.name):
        if not chunk:
            continue
        words = {w.lower() for w in re.split(r"[ _\-.]+", chunk) if w}
        hits = [by_lower[w] for w in words if w in by_lower]
        if hits:
            return max(hits, key=len)
    return ""
