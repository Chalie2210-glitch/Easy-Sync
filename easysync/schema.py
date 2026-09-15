# -*- coding: utf-8 -*-
"""Wwise 스키마 어휘 — 루트 경로 해석과 임포트 타입 토큰.

여기 있는 토큰은 전부 Wwise 2025.1.8(schema 133)에 실제로 임포트를 날려서
확인한 것이다. 추측한 항목은 없다. 확인 방법과 결과는 README 의
"검증된 동작" 절에 있다.

두 어휘를 절대 섞지 말 것:

  * 임포트 토큰 — ``objectPath`` 안의 ``<...>`` 에 들어가는 표시 이름.
    ``<Random Container>``, ``<Sound SFX>`` 처럼 공백이 있는 사람용 이름이다.
  * 조회 타입 — ``object.get`` 이 ``type`` 으로 돌려주는 이름.
    ``RandomSequenceContainer``, ``Sound`` 처럼 붙여 쓴 이름이다.

둘은 다대일로 접힌다. ``Random Container`` 와 ``Sequence Container`` 는 둘 다
``RandomSequenceContainer`` 로 읽히고, ``Sound SFX`` 와 ``Sound Voice`` 는 둘 다
``Sound`` 로 읽힌다. 그래서 조회 타입 하나만 보고 임포트 토큰을 되돌리는 함수는
만들지 않는다 — 만들면 누군가 보이스를 SFX 로 임포트하게 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 임포트 토큰 -> 조회 타입.  전부 2025.1.8 에서 실측 확인.
# ---------------------------------------------------------------------------
IMPORT_TO_QUERY: dict[str, str] = {
    "Random Container": "RandomSequenceContainer",
    "Sequence Container": "RandomSequenceContainer",
    "Switch Container": "SwitchContainer",
    "Blend Container": "BlendContainer",
    "Actor-Mixer": "PropertyContainer",
    "Property Container": "PropertyContainer",
    "Virtual Folder": "Folder",
    "Folder": "Folder",
    "Work Unit": "WorkUnit",
    "Sound SFX": "Sound",
    "Sound Voice": "Sound",
    "Sound": "Sound",
}

#: 타입 토큰을 생략한 경로 세그먼트가 실제로 만들어지는 타입. 실측 확인.
UNTYPED_SEGMENT_TYPE = "Folder"

#: 사용자가 그룹 묶음으로 고를 수 있는 컨테이너. (임포트 토큰, 한글 표시 이름)
#: 순서가 곧 UI 표시 순서이고, 첫 항목이 기본값이다 — 개발문서의 "기본으로
#: 랜덤컨테이너가 선택되고".
GROUP_CONTAINERS: list[tuple[str, str]] = [
    ("Random Container", "랜덤 컨테이너"),
    ("Sequence Container", "시퀀스 컨테이너"),
    ("Switch Container", "스위치 컨테이너"),
    ("Blend Container", "블렌드 컨테이너"),
    ("Actor-Mixer", "액터 믹서"),
    ("Virtual Folder", "가상 폴더"),
]

#: 그룹을 묶지 않고 파일을 그대로 개별 Sound 로 넣는 선택지.
NO_CONTAINER = ""

#: 임포트할 Sound 의 타입 토큰. SFX 와 보이스는 importLanguage 로도 갈린다.
SOUND_SFX = "Sound SFX"
SOUND_VOICE = "Sound Voice"

#: 트리에서 임포트 대상(부모)이 될 수 있는 조회 타입.
#: 2023 의 ActorMixer 와 2025 의 PropertyContainer 를 둘 다 넣어 둔다 —
#: 한쪽만 넣으면 Wwise 버전이 바뀔 때 트리가 통째로 비어 보인다.
DESTINATION_TYPES: frozenset[str] = frozenset({
    "WorkUnit", "Folder", "PropertyContainer", "ActorMixer",
    "RandomSequenceContainer", "SwitchContainer", "BlendContainer",
})

#: 트리에서 펼칠 수 있는 타입 — 대상 타입에 Sound 를 더한 것.
EXPANDABLE_TYPES: frozenset[str] = DESTINATION_TYPES | {"Sound"}

#: Originals 하위 경로에 포함시킬 수 있는 계층 타입.
#: (설정 키, 한글 표시 이름, 여기에 해당하는 조회 타입들)
#:
#: Wwise 오브젝트 경로를 Originals 폴더에 그대로 미러링하되, 여기서 체크한
#: 타입의 세그먼트만 폴더가 된다. 보통 Work Unit·폴더·액터믹서는 폴더로
#: 만들고, 랜덤/스위치 컨테이너는 만들지 않는다 — 컨테이너는 재생 구조지
#: 파일 정리 구조가 아니기 때문이다.
ORIGINALS_SUBPATH_TYPES: list[tuple[str, str, frozenset[str]]] = [
    ("work_unit", "Work Unit", frozenset({"WorkUnit"})),
    ("virtual_folder", "가상 폴더", frozenset({"Folder"})),
    ("actor_mixer", "프로퍼티 컨테이너 / 액터 믹서",
     frozenset({"PropertyContainer", "ActorMixer"})),
    ("random_sequence", "랜덤 / 시퀀스 컨테이너",
     frozenset({"RandomSequenceContainer"})),
    ("switch", "스위치 컨테이너", frozenset({"SwitchContainer"})),
    ("blend", "블렌드 컨테이너", frozenset({"BlendContainer"})),
    ("music_switch", "뮤직 스위치 컨테이너", frozenset({"MusicSwitchContainer"})),
    ("music_playlist", "뮤직 플레이리스트 컨테이너",
     frozenset({"MusicPlaylistContainer"})),
    ("music_segment", "뮤직 세그먼트", frozenset({"MusicSegment"})),
]

#: 기본으로 켜 두는 하위 경로 타입.
DEFAULT_ORIGINALS_SUBPATH_KEYS: list[str] = ["virtual_folder", "actor_mixer"]


def subpath_query_types(keys: list[str]) -> frozenset[str]:
    """설정 키 목록을 조회 타입 집합으로 바꾼다."""
    chosen = set(keys)
    out: set[str] = set()
    for key, _label, types in ORIGINALS_SUBPATH_TYPES:
        if key in chosen:
            out |= types
    return frozenset(out)


#: Play 액션의 @ActionType 값. 실측 확인.
ACTION_TYPE_PLAY = 1

#: 비(非)보이스 임포트를 뜻하는 importLanguage 센티넬 값.
LANGUAGE_SFX = "SFX"

#: 경로 구분자. Wwise 오브젝트 경로는 항상 역슬래시다.
SEP = "\\"


@dataclass
class Roots:
    """프로젝트에서 해석한 계층 루트.

    하드코딩하지 않는 이유: 2025.1 에서 ``Actor-Mixer Hierarchy`` 가
    ``Containers`` 로 바뀌었다. ``getProjectInfo`` 의 ``defaultWorkUnits`` 를
    읽으면 버전을 몰라도 맞는 이름이 나온다.
    """

    containers: str = SEP + "Containers"
    events: str = SEP + "Events"
    switches: str = SEP + "Switches"
    states: str = SEP + "States"
    #: 기본 Work Unit 의 전체 경로. 트리를 처음 펼칠 때 여기로 이동한다.
    containers_default_wu: str = ""
    events_default_wu: str = ""
    #: getProjectInfo 가 알려주지 않은 키가 있었으면 True.
    partial: bool = False
    missing: list[str] = field(default_factory=list)


def _root_of(path: str) -> str:
    """``Containers\\Default Work Unit`` 에서 첫 세그먼트만 떼어 온다.

    "Default Work Unit" 이라는 이름을 문자열로 찾지 않는다. 그 Work Unit 은
    이름을 바꿀 수 있고 언어에 따라 다르게 표시된다.
    """
    parts = [p for p in path.split(SEP) if p]
    return SEP + parts[0] if parts else ""


def resolve_roots(project_info: dict) -> Roots:
    """``getProjectInfo`` 응답에서 계층 루트를 뽑는다."""
    wu = project_info.get("defaultWorkUnits") or {}
    roots = Roots()
    missing: list[str] = []

    def pick(keys: list[str], fallback: str, label: str) -> tuple[str, str]:
        for key in keys:
            entry = wu.get(key)
            if isinstance(entry, dict):
                full = entry.get("path") or ""
                root = _root_of(full)
                if root:
                    return root, full
        missing.append(label)
        return fallback, ""

    # 키 순서가 의미를 가진다: 신버전 키를 먼저, 구버전 키를 뒤에.
    roots.containers, roots.containers_default_wu = pick(
        ["Containers", "Actor-Mixer Hierarchy", "ActorMixer"],
        Roots.containers, "오디오 계층")
    roots.events, roots.events_default_wu = pick(["Events"], Roots.events, "이벤트")
    roots.switches, _ = pick(["Switches"], Roots.switches, "스위치")
    roots.states, _ = pick(["States"], Roots.states, "스테이트")
    roots.missing = missing
    roots.partial = bool(missing)
    return roots


def is_group_container(token: str) -> bool:
    return token in dict(GROUP_CONTAINERS)


def display_name(token: str) -> str:
    """임포트 토큰의 한글 표시 이름. 모르는 토큰은 그대로 돌려준다."""
    return dict(GROUP_CONTAINERS).get(token, token or "컨테이너 없음")
