# -*- coding: utf-8 -*-
"""Wwise 오브젝트 아이콘.

Wwise 설치 폴더의 공식 아이콘(``Data/Themes/<테마>/images/ObjectIcons``)을
그대로 읽는다. 아이콘을 저장소에 복사하지 않는 이유가 둘 있다.

  * Audiokinetic 자산이다. 우리 저장소에 사본을 두고 배포할 이유가 없다.
  * 설치된 Wwise 에서 직접 읽으면 버전이 올라가 아이콘이 바뀌어도 자동으로
    따라간다. 사용자가 Wwise 에서 보는 그림과 이 툴에서 보는 그림이 항상
    같아야 헷갈리지 않는다.

Wwise 를 못 찾거나 아이콘이 없으면 조용히 빈 아이콘을 돌려준다. 아이콘은
장식이지 기능이 아니므로 이것 때문에 툴이 뜨지 않으면 안 된다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QIcon

log = logging.getLogger(__name__)

#: 조회 타입 -> Wwise 아이콘 파일 이름(접두사/접미사 제외).
#: 랜덤과 시퀀스는 조회 타입이 같으므로(RandomSequenceContainer) 여기서
#: 나누지 못한다. @RandomOrSequence 를 보고 for_object 가 갈라 준다.
_BY_TYPE: dict[str, str] = {
    "WorkUnit": "Workunit",
    "Folder": "Folder",
    "PhysicalFolder": "PhysicalFolder",
    "ActorMixer": "ActorMixer",
    "PropertyContainer": "ActorMixer",
    "RandomSequenceContainer": "RandomContainer",
    "SwitchContainer": "SwitchContainer",
    "BlendContainer": "BlendContainer",
    "Sound": "SoundFX",
    "AudioFileSource": "AudioFile",
    "Event": "Event",
    "Action": "ActionPlay",
    "SwitchGroup": "SwitchGroup",
    "StateGroup": "StateGroup",
    "Switch": "Switch",
    "State": "State",
    "MusicSegment": "MusicSegment",
    "MusicTrack": "MusicTrack",
    "MusicSwitchContainer": "MusicSwitchContainer",
    "MusicPlaylistContainer": "MusicRandomSequenceContainer",
    "MusicRandomSequenceContainer": "MusicRandomSequenceContainer",
    "Bus": "Bus",
    "AuxBus": "AuxBus",
}

#: 임포트 토큰 -> 아이콘 이름. 토큰은 랜덤/시퀀스를 구분할 수 있다.
_BY_TOKEN: dict[str, str] = {
    "Random Container": "RandomContainer",
    "Sequence Container": "SequenceContainer",
    "Switch Container": "SwitchContainer",
    "Blend Container": "BlendContainer",
    "Actor-Mixer": "ActorMixer",
    "Property Container": "ActorMixer",
    "Virtual Folder": "Folder",
    "Folder": "Folder",
    "Work Unit": "Workunit",
    "Sound SFX": "SoundFX",
    "Sound Voice": "SoundVoice",
    "Sound": "SoundFX",
}

_cache: dict[str, QIcon] = {}
_icon_dir: Path | None = None
_searched = False


def configure(install_dir: str | Path | None, theme: str = "dark") -> bool:
    """아이콘 폴더를 정한다. 찾았으면 True.

    ``install_dir`` 은 ``ak.wwise.core.getInfo`` 의 ``directories.install``.
    """
    global _icon_dir, _searched, _cache
    _searched = True
    _cache = {}
    if not install_dir:
        _icon_dir = None
        return False
    base = Path(install_dir) / "Authoring" / "Data" / "Themes"
    for name in (theme, "dark", "classic", "light"):
        candidate = base / name / "images" / "ObjectIcons"
        if candidate.is_dir():
            _icon_dir = candidate
            log.info("Wwise 아이콘 폴더: %s", candidate)
            return True
    log.warning("Wwise 아이콘 폴더를 찾지 못했습니다: %s", base)
    _icon_dir = None
    return False


def _load(name: str) -> QIcon:
    if name in _cache:
        return _cache[name]
    icon = QIcon()
    if _icon_dir is not None:
        for suffix in (".svg", ".png"):
            path = _icon_dir / f"ObjectIcons_{name}_nor{suffix}"
            if path.exists():
                icon = QIcon(str(path))
                break
        else:
            log.debug("아이콘 없음: %s", name)
    _cache[name] = icon
    return icon


def for_type(query_type: str) -> QIcon:
    """조회 타입에 맞는 아이콘."""
    name = _BY_TYPE.get(query_type)
    return _load(name) if name else QIcon()


def for_object(row: dict) -> QIcon:
    """``object.get`` 이 돌려준 행에 맞는 아이콘.

    랜덤/시퀀스는 타입이 같으므로 ``@RandomOrSequence`` 로 가른다
    (0 = 시퀀스, 1 = 랜덤 — 실측 확인).
    """
    kind = row.get("type", "")
    if kind == "RandomSequenceContainer":
        return _load("RandomContainer" if row.get("@RandomOrSequence") == 1
                     else "SequenceContainer")
    if kind == "Sound":
        # 보이스인지 SFX 인지는 조회 타입만으로 알 수 없다. 기본은 SFX.
        return _load("SoundFX")
    return for_type(kind)


def for_token(token: str) -> QIcon:
    """임포트 토큰(``Random Container`` 등)에 맞는 아이콘."""
    name = _BY_TOKEN.get(token)
    return _load(name) if name else QIcon()


def available() -> bool:
    return _icon_dir is not None
