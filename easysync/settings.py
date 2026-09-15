# -*- coding: utf-8 -*-
"""사용자 설정 저장.

``%APPDATA%\\EasySync\\settings.json`` 에 둔다. 툴 폴더가 아니라 APPDATA 인
이유: zip 을 다시 풀거나 빌드를 새로 받아도 핀과 기본값이 살아남아야 한다.

쓰기는 임시 파일에 쓴 뒤 ``os.replace`` 로 바꾼다. 저장 도중 툴이 죽어도
설정 파일이 반쯤 쓰인 채로 남지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .schema import DEFAULT_ORIGINALS_SUBPATH_KEYS

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EasySync"
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass
class Settings:
    """창을 다시 열었을 때 이어서 작업할 수 있게 하는 값들."""

    #: 작업자별 관심 경로. 오디오 트리를 이 하위로만 좁혀 보여준다.
    pins: list[str] = field(default_factory=list)
    #: 이벤트 트리의 핀.
    event_pins: list[str] = field(default_factory=list)
    #: 마지막으로 임포트한 목적지.
    last_destination: str = ""
    #: 마지막 이벤트 경로.
    last_event_root: str = ""
    #: 파일 이름의 단어로 임포트 위치를 추천할지.
    #: 추천일 뿐이라 누르기 전에는 아무것도 바뀌지 않는다.
    suggest_paths: bool = False
    #: 가져온 파일을 이름 규칙으로 자동으로 묶을지.
    #:
    #: 기본은 끔. 자동 묶기는 이름만 보고 하는 추측이라 틀릴 때가 있는데,
    #: 켜져 있는 것이 기본이면 사용자는 "왜 멋대로 묶였지" 부터 풀어야 한다.
    #: 꺼 두면 일단 그대로 들어오고, 묶고 싶을 때만 묶으면 된다.
    auto_group: bool = False
    #: 자동으로 묶였을 때 붙는 컨테이너 타입(임포트 토큰).
    default_container: str = "Random Container"
    #: createNew / useExisting / replaceExisting
    import_operation: str = "useExisting"
    #: 보이스로 임포트할지 여부.
    is_voice: bool = False
    #: Originals 경로를 정하는 방식.
    #:   "smart"  — Wwise 계층을 따라 자동으로 만든다
    #:   "manual" — 임포트할 때 탐색기로 직접 고른다
    originals_mode: str = "smart"
    #: Originals 기준 폴더. 계층 경로 앞에 붙는다.
    originals_subfolder: str = ""
    #: Originals 하위 경로로 따라갈 계층 타입 (schema.ORIGINALS_SUBPATH_TYPES 의 키).
    originals_subpath_keys: list[str] = field(
        default_factory=lambda: list(DEFAULT_ORIGINALS_SUBPATH_KEYS))
    window_geometry: str = ""
    defaults_version: int = 1

    @classmethod
    def load(cls) -> "Settings":
        """설정을 읽는다. 없거나 깨졌으면 기본값을 돌려준다.

        모르는 키는 무시한다 — 옛 버전이 남긴 설정 때문에 툴이 뜨지 않으면
        안 된다.
        """
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("설정을 읽지 못해 기본값을 씁니다: %s", exc)
            return cls()
        if raw.get("defaults_version", 0) < 1:
            raw.update(default_container="Random Container", suggest_paths=False,
                       defaults_version=1)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_PATH.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8")
            os.replace(tmp, SETTINGS_PATH)
        except OSError as exc:
            log.warning("설정 저장 실패: %s", exc)
