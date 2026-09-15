# -*- coding: utf-8 -*-
"""미리보기 계획 — 임포트 전에 무엇이 만들어지는지 계산한다.

이 모듈은 WAAPI 를 부르지 않는다. 순수 계산이라 테스트하기 쉽고, 무엇보다
"실행하기 전에 보여준다" 는 요구사항이 실제로 지켜지는지 확인할 수 있다.
UI 는 여기서 나온 트리를 그리고, 임포트 단계는 여기서 나온 payload 를 그대로
보낸다. 미리보기와 실제 실행이 **같은 자료구조**에서 나오므로 둘이 어긋날 수
없다 — 이게 이 설계의 핵심이다.

용어:
  * 목적지(destination) — 사용자가 트리에서 고른 부모 오브젝트의 경로.
  * 그룹(group)         — 컨테이너 하나로 묶일 파일 묶음.
  * 계획 노드(PlanNode) — 미리보기 트리에 그려질 항목 하나.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import naming
from .schema import IMPORT_TO_QUERY, SEP, NO_CONTAINER, SOUND_SFX, SOUND_VOICE

# 계획 노드의 상태. 미리보기에서 색으로 구분된다.
NEW = "new"            # 새로 만들어진다
EXISTING = "existing"  # 이미 있다. 옵션에 따라 재사용/교체/새로 생성
REPLACE = "replace"    # 이미 있고 오디오를 교체한다
RENAME = "rename"      # 이미 있어서 다른 이름(_01)으로 새로 만들어진다


@dataclass(eq=False)
class SourceFile:
    """임포트 대상 오디오 파일 하나.

    ``eq=False`` 로 정체성 비교를 쓴다. 기본 동작(필드 비교)이면 같은
    이름·설정을 가진 서로 다른 파일이 동등해져서, UI 의
    ``files.remove(source)`` 가 고른 것이 아닌 다른 줄을 지운다.
    """

    path: Path
    include: bool = True
    #: 단계별 스위치/스테이트 이름. 묶음의 ``switch_levels`` 와 같은 순서다.
    #: 1단계면 ["Sand"], 2단계면 ["Sand", "Walk"].
    switches: list[str] = field(default_factory=list)
    #: Wwise 에 만들어질 Sound 이름. 비어 있으면 파일 이름에서 만든다.
    object_name: str = ""

    def switch_at(self, level: int) -> str:
        """그 단계의 스위치 이름. 아직 없으면 빈 문자열."""
        return self.switches[level] if level < len(self.switches) else ""

    def set_switch_at(self, level: int, value: str) -> None:
        while len(self.switches) <= level:
            self.switches.append("")
        self.switches[level] = value

    @property
    def stem(self) -> str:
        return naming.strip_extension(self.path.name)

    @property
    def name(self) -> str:
        # 복제 꼬리표(" - 복사본")를 뗀 이름을 쓴다. 사용자가 트리에서
        # 직접 고쳤으면 그 값이 우선한다.
        return self.object_name or naming.object_name(self.path.name)


@dataclass(eq=False)
class Group:
    """컨테이너 하나로 묶일 파일 묶음.

    ``eq=False`` 인 이유는 :class:`SourceFile` 과 같다 — UI 가 ``index``/
    ``remove``/``in`` 으로 특정 묶음을 집어내므로 정체성 비교여야 한다.

    ``container`` 가 비어 있으면(``NO_CONTAINER``) 컨테이너를 만들지 않고
    파일을 목적지 바로 아래에 개별 Sound 로 넣는다.
    """

    key: str
    files: list[SourceFile] = field(default_factory=list)
    container: str = "Random Container"
    make_event: bool = False
    event_name: str = ""
    #: 스위치 컨테이너일 때 연결할 스위치/스테이트 그룹 경로들.
    #:
    #: 여러 개를 넣으면 그만큼 계층이 깊어진다. ``[Surface, Speed]`` 면
    #: 바깥 컨테이너가 Surface 로 갈리고, 그 안의 값별 컨테이너가 다시
    #: Speed 로 갈린다 — Wwise 에서 손으로 만드는 구조와 같다.
    switch_levels: list[str] = field(default_factory=list)

    @property
    def included(self) -> list[SourceFile]:
        return [f for f in self.files if f.include]

    @property
    def switch_group(self) -> str:
        """첫 단계 스위치 그룹. 단계가 없으면 빈 문자열."""
        return self.switch_levels[0] if self.switch_levels else ""

    @property
    def switch_depth(self) -> int:
        return len(self.switch_levels)

    def resolved_event_name(self) -> str:
        return self.event_name or naming.default_event_name(self.key)


@dataclass
class SwitchBinding:
    """스위치 컨테이너 하나에 대한 배정 지시.

    임포트가 끝난 뒤 실행된다 — 컨테이너와 자식이 실제로 생긴 다음에야
    id 로 묶을 수 있기 때문이다.
    """

    #: 이 스위치 컨테이너의 경로.
    container_path: str
    #: 여기에 연결할 스위치/스테이트 그룹 경로.
    switch_group: str
    #: 자식 이름 -> 배정할 스위치 이름.
    children: dict[str, str] = field(default_factory=dict)


@dataclass
class PlanNode:
    """미리보기 트리의 노드 하나."""

    name: str
    type_token: str
    status: str = NEW
    path: str = ""
    children: list["PlanNode"] = field(default_factory=list)
    #: 이 노드를 만들어 내는 원본 파일 (Sound 노드에만 있다).
    source: Path | None = None
    note: str = ""
    #: 원본 wav 가 복사될 Originals 하위 경로 (Sound 노드에만 있다).
    originals: str = ""


@dataclass
class Issue:
    """사용자가 임포트 전에 고쳐야 할 문제."""

    level: str      # "error" | "warning"
    message: str


@dataclass
class Plan:
    """계산된 계획 전체."""

    destination: str
    nodes: list[PlanNode] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    #: (그룹, 컨테이너 경로) — 이벤트를 만들 대상. 임포트 후에 처리한다.
    events: list[tuple[Group, str]] = field(default_factory=list)
    #: 임포트 뒤에 실행할 스위치 배정.
    switch_bindings: list[SwitchBinding] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    file_count: int = 0
    container_count: int = 0
    event_count: int = 0

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    @property
    def is_empty(self) -> bool:
        return not self.imports


def _typed(token: str, name: str) -> str:
    """``<Random Container>MyName`` 형태의 경로 세그먼트를 만든다.

    토큰이 비어 있으면 타입을 지정하지 않는다. 그 경우 Wwise 는 Folder 를
    만든다(실측 확인). 그래서 목적지 아래에 폴더가 생기길 원하지 않는다면
    빈 토큰을 넘기면 안 된다.
    """
    return f"<{token}>{name}" if token else name


def originals_subpath(
    destination_segments: list[tuple[str, str]],
    container: tuple[str, str] | None,
    subpath_types: frozenset[str],
    base: str = "",
) -> str:
    """Wwise 계층을 Originals 폴더 경로로 미러링한다.

    체크된 타입의 세그먼트만 폴더가 된다. 예를 들어 폴더와 액터믹서만
    체크했다면::

        Wwise      \\Containers\\Audio\\NPC\\Creature_Voice\\Creature_Voice(랜덤)\\Sound
        Originals  Originals\\SFX\\NPC\\Creature_Voice\\Sound.wav
                                    └ Work Unit(Audio)과 랜덤 컨테이너는 빠짐

    ``base`` 가 있으면 앞에 붙는다. 팀 규칙으로 고정 접두 폴더를 두는 경우가
    있어서다.
    """
    parts: list[str] = []
    if base:
        parts.extend(p for p in base.replace("/", SEP).split(SEP) if p)
    for name, kind in destination_segments:
        if kind in subpath_types:
            parts.append(name)
    if container is not None:
        name, kind = container
        if kind in subpath_types:
            parts.append(name)
    # 세그먼트 이름은 폴더 이름이 된다. Wwise 이름에 허용되지만 Windows
    # 폴더명으로는 못 쓰는 문자가 섞일 수 있으니 한 번 더 정리한다.
    return SEP.join(naming.sanitized(p) for p in parts)


def build(
    groups: list[Group],
    destination: str,
    *,
    existing_paths: frozenset[str] = frozenset(),
    import_operation: str = "useExisting",
    is_voice: bool = False,
    language: str = "SFX",
    originals_subfolder: str = "",
    destination_segments: list[tuple[str, str]] | None = None,
    originals_subpath_types: frozenset[str] = frozenset(),
) -> Plan:
    """그룹 목록에서 계획을 만든다.

    ``existing_paths`` 는 Wwise 에 이미 있는 오브젝트 경로의 집합(소문자)이다.
    비어 있으면 "모르는 상태"로 취급해 전부 새로 만드는 것으로 표시한다 —
    없는 것을 있다고 하는 것보다 낫다.

    ``import_operation`` 은 UI의 세 가지 동작을 표시한다. WAAPI 변환은 payload에서 한다:
      * ``createNew``      — 이름이 겹치면 ``_01`` 을 붙여 새로 만든다
      * ``useExisting``    — 이미 있으면 그대로 두고 오디오를 다시 넣지 않는다
      * ``replaceExisting``— 이미 있으면 오디오 소스를 교체한다
    """
    plan = Plan(destination=destination)
    sound_token = SOUND_VOICE if is_voice else SOUND_SFX
    lower_existing = existing_paths

    if not destination:
        plan.issues.append(Issue("error", "임포트할 위치를 왼쪽 트리에서 선택하세요."))
        return plan

    def status_for(path: str) -> str:
        if path.lower() not in lower_existing:
            return NEW
        if import_operation == "createNew":
            return RENAME
        if import_operation == "replaceExisting":
            return REPLACE
        return EXISTING

    seen_paths: dict[str, str] = {}   # 소문자 경로 -> 원본 파일 표시용

    for group in groups:
        files = group.included
        if not files:
            continue

        # 이 그룹의 파일들이 들어갈 Originals 하위 경로.
        # 타입이 하나도 체크되지 않았으면 미러링을 끈 것으로 보고 예전처럼
        # 수동 입력값만 쓴다.
        if originals_subpath_types:
            container_segment = None
            if group.container != NO_CONTAINER:
                container_segment = (
                    naming.sanitized(group.key),
                    IMPORT_TO_QUERY.get(group.container, ""))
            subfolder = originals_subpath(
                destination_segments or [], container_segment,
                originals_subpath_types, originals_subfolder)
        else:
            subfolder = originals_subfolder

        use_container = group.container != NO_CONTAINER
        if use_container:
            container_name = naming.sanitize(group.key)
            if container_name.changed:
                plan.issues.append(Issue(
                    "warning",
                    f"컨테이너 이름 '{group.key}' 에 쓸 수 없는 문자가 있어 "
                    f"'{container_name.value}' 로 정리했습니다."))
            container_path = destination + SEP + container_name.value
            container_node = PlanNode(
                name=container_name.value,
                type_token=group.container,
                status=status_for(container_path),
                path=container_path,
            )
            plan.nodes.append(container_node)
            plan.container_count += 1
            parent_segment = _typed(group.container, container_name.value)
            parent_path = container_path
            child_holder = container_node.children
        else:
            parent_segment = ""
            parent_path = destination
            child_holder = plan.nodes
            container_path = destination

        # 스위치 단계가 둘 이상이면 값마다 컨테이너가 한 겹씩 더 생긴다.
        # Wwise 에서 손으로 만드는 구조와 같다:
        #   Footstep(Surface) > Sand(Speed) > Sand_Walk_01
        is_switch = use_container and group.container == "Switch Container"
        levels: list[str] = []
        if is_switch:
            # 빈 단계에서 끊는다. 걸러 내면 그 뒤 단계의 번호가 하나씩
            # 당겨져 파일이 엉뚱한 그룹에 배정된다.
            for level_path in group.switch_levels:
                if not level_path:
                    break
                levels.append(level_path)
        # 경로별 배정 지시. 중간 컨테이너 하나를 여러 파일이 나눠 쓰므로
        # 경로를 열쇠로 모아 둔다.
        bindings: dict[str, SwitchBinding] = {}
        branch_nodes: dict[str, PlanNode] = {}
        unassigned: list[str] = []
        if levels:
            bindings[container_path] = SwitchBinding(
                container_path=container_path, switch_group=levels[0])

        for source in files:
            clean = naming.sanitize(source.name)
            if clean.changed:
                plan.issues.append(Issue(
                    "warning",
                    f"오브젝트 이름 '{source.name}' 을 '{clean.value}' 로 정리했습니다."))

            # 마지막 단계는 Sound 자신이 배정되므로 중간 컨테이너는 단계
            # 수보다 하나 적다. 중간에 값이 비면 거기서 멈춘다 — 이름 없는
            # 컨테이너를 만드는 것보다 얕게 두는 편이 고치기 쉽다.
            branch: list[str] = []
            for level in range(len(levels) - 1):
                # 빈 값을 sanitize 하면 'Unnamed' 가 나온다. 그 이름으로
                # 컨테이너를 만들면 안 되므로 원본을 먼저 본다.
                raw = source.switch_at(level)
                value = naming.sanitized(raw) if raw else ""
                if not value:
                    plan.issues.append(Issue(
                        "warning",
                        f"'{source.name}' 의 {level + 1}단계 스위치가 비어 있어 "
                        f"그 아래 계층 없이 만들어집니다."))
                    break
                branch.append(value)

            # 단계를 따라 내려가며 중간 컨테이너를 만들고, 지나온 컨테이너에
            # 자식 배정을 기록한다.
            branch_path = parent_path
            holder = child_holder
            here = bindings.get(container_path)
            for depth, value in enumerate(branch):
                if here is not None:
                    # 컨테이너 이름이 곧 배정될 스위치 값이다.
                    here.children[value] = source.switch_at(depth)
                branch_path += SEP + value
                node_here = branch_nodes.get(branch_path.lower())
                if node_here is None:
                    node_here = PlanNode(
                        name=value,
                        type_token="Switch Container",
                        status=status_for(branch_path),
                        path=branch_path,
                    )
                    holder.append(node_here)
                    branch_nodes[branch_path.lower()] = node_here
                    plan.container_count += 1
                    bindings[branch_path] = SwitchBinding(
                        container_path=branch_path,
                        switch_group=levels[depth + 1])
                holder = node_here.children
                here = bindings.get(branch_path)

            sound_path = branch_path + SEP + clean.value

            # 같은 계획 안에서 두 파일이 같은 경로로 가면 하나가 다른 하나를
            # 덮어쓴다. Wwise 는 대소문자만 다른 형제를 허용하지 않으므로
            # 비교도 소문자로 한다.
            key = sound_path.lower()
            if key in seen_paths:
                plan.issues.append(Issue(
                    "error",
                    f"경로가 겹칩니다: '{sound_path}' 에 "
                    f"'{seen_paths[key]}' 와 '{source.path.name}' 이 함께 배정되었습니다."))
            else:
                seen_paths[key] = source.path.name

            if not source.path.exists():
                plan.issues.append(Issue(
                    "error", f"파일을 찾을 수 없습니다: {source.path}"))

            node = PlanNode(
                name=clean.value,
                type_token=sound_token,
                status=status_for(sound_path),
                path=sound_path,
                source=source.path,
            )
            if is_switch:
                # 소리 자신이 배정될 단계는 지나온 깊이 바로 다음이다.
                leaf = source.switch_at(len(branch)) if levels else ""
                if leaf and here is not None:
                    here.children[clean.value] = leaf
                elif levels:
                    unassigned.append(source.name)
                chain = [v for v in (list(branch) + [leaf]) if v]
                node.note = " > ".join(chain) if chain else "(스위치 미지정)"
            holder.append(node)

            object_path = destination
            if parent_segment:
                object_path += SEP + parent_segment
            for value in branch:
                object_path += SEP + _typed("Switch Container", value)
            object_path += SEP + _typed(sound_token, clean.value)

            # 중간 스위치 컨테이너도 계층의 일부다. 스위치 컨테이너를
            # 미러링하기로 했다면 안쪽 것도 같이 폴더가 되어야 바깥만
            # 폴더이고 안은 평평한 어정쩡한 모양이 나오지 않는다.
            file_subfolder = subfolder
            if branch and "SwitchContainer" in originals_subpath_types:
                file_subfolder = SEP.join(
                    [part for part in [subfolder, *branch] if part])
            if file_subfolder:
                entry_subfolder = file_subfolder
            else:
                entry_subfolder = ""

            entry: dict = {
                "audioFile": str(source.path),
                "objectPath": object_path,
            }
            if entry_subfolder:
                entry["originalsSubFolder"] = entry_subfolder
            node.originals = entry_subfolder
            plan.imports.append(entry)
            plan.file_count += 1

        if use_container and group.make_event:
            plan.events.append((group, container_path))
            plan.event_count += 1
        elif group.make_event and not use_container:
            # 컨테이너 없이 이벤트를 켜면 파일마다 이벤트가 하나씩 생긴다.
            # 그게 사용자가 원한 것인지 확실하지 않으니 알려 준다.
            plan.issues.append(Issue(
                "warning",
                f"'{group.key}' 는 컨테이너 없이 이벤트가 켜져 있어 "
                f"파일 {len(files)}개마다 이벤트가 하나씩 만들어집니다."))
            for source in files:
                plan.events.append((group, parent_path + SEP + naming.sanitized(source.name)))
                plan.event_count += 1

        if is_switch:
            if not levels:
                plan.issues.append(Issue(
                    "warning",
                    f"'{group.key}' 는 스위치 컨테이너인데 스위치 그룹이 "
                    f"지정되지 않아 배정 없이 만들어집니다."))
            else:
                if unassigned:
                    plan.issues.append(Issue(
                        "warning",
                        f"'{group.key}' 의 파일 {len(unassigned)}개는 스위치가 "
                        f"지정되지 않아 어느 값에도 배정되지 않습니다."))
                plan.switch_bindings.extend(bindings.values())

    if not plan.imports:
        plan.issues.append(Issue("error", "임포트할 파일이 없습니다."))

    return plan


def import_entry_path(entry: dict, destination: str) -> str:
    """Strip import type tokens only after the existing destination path."""
    path = entry["objectPath"]
    return destination + re.sub(r"<[^>]+>", "", path[len(destination):])


def payload(plan: Plan, *, import_operation: str, language: str,
            existing_paths: frozenset[str] | None = None) -> dict:
    """Translate user modes into safe WAAPI operations.

    UI replaceExisting means audio-only update: WAAPI useExisting preserves IDs.
    UI useExisting means skip existing sounds entirely; WAAPI useExisting alone
    would overwrite their audio, despite the UI's promise to keep it unchanged.
    """
    if existing_paths is None:
        def walk(nodes):
            for node in nodes:
                if node.status != NEW:
                    yield node.path.lower()
                yield from walk(node.children)
        existing_paths = frozenset(walk(plan.nodes))
    entries = list(plan.imports)
    if import_operation == "useExisting":
        entries = [e for e in entries
                   if import_entry_path(e, plan.destination).lower() not in existing_paths]
    return {
        "importOperation": "useExisting" if import_operation == "replaceExisting"
                           else import_operation,
        "default": {"importLanguage": language},
        "imports": entries,
    }


def flat_files(paths: list[Path]) -> list[Group]:
    """묶지 않고 파일 하나당 낱개 항목을 만든다.

    기본 동작이다. 자동 묶기는 이름만 보고 하는 추측이라, 켜져 있는 것이
    기본이면 사용자가 "왜 멋대로 묶였지" 부터 풀어야 한다. 일단 그대로
    들여놓고, 묶는 것은 고르고 나서 한다.

    낱개도 :class:`Group` 으로 표현한다 — 담는 그릇이 하나여야 묶고 푸는
    것이 단순한 이동이 되기 때문이다. 컨테이너가 없으면(``NO_CONTAINER``)
    화면에는 낱개 파일 한 줄로 보인다.
    """
    return [Group(key=naming.object_name(path.name),
                  files=[SourceFile(path=path)],
                  container=NO_CONTAINER)
            for path in sorted(paths, key=lambda p: naming.natural_key(p.name))]


def group_files(
    paths: list[Path], container: str = "Random Container",
    *, auto: bool = True
) -> list[Group]:
    """파일 목록을 이름 규칙으로 묶는다.

    ``auto=False`` 면 묶지 않고 낱개로 둔다.

    묶을 때도 **혼자 남는 파일은 컨테이너를 씌우지 않는다.** 파일 하나짜리
    랜덤 컨테이너는 아무 의미가 없고, 지우는 손이 한 번 더 간다.

    처음 나온 순서를 유지한다. 사용자가 파일 탐색기에서 고른 순서에는 의미가
    있을 때가 많고, 알파벳순으로 재정렬하면 그 의도가 사라진다.
    """
    if not auto:
        return flat_files(paths)

    order: list[str] = []
    buckets: dict[str, list[Path]] = {}
    for path in sorted(paths, key=lambda p: naming.natural_key(p.name)):
        key = naming.group_key(path.name)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(path)

    groups: list[Group] = []
    for key in order:
        paths_in = buckets[key]
        files = [SourceFile(path=p) for p in paths_in]
        if len(files) == 1:
            # 혼자면 묶지 않는다. 이름도 파일 이름 그대로 둔다 —
            # 인덱스를 뗀 이름(key)은 묶였을 때만 의미가 있다.
            groups.append(Group(key=files[0].name, files=files,
                                container=NO_CONTAINER))
        else:
            groups.append(Group(key=key, files=files, container=container))
    return groups
