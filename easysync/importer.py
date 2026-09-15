# -*- coding: utf-8 -*-
"""실행 단계 — 계획을 실제 Wwise 변경으로 옮긴다.

``plan.build`` 가 만든 계획을 그대로 받아 실행한다. 미리보기에 보인 것과
실행되는 것이 같은 자료구조에서 나오므로 둘이 어긋날 수 없다.

전체를 하나의 undo 그룹으로 감싼다. 사운드 디자이너가 임포트 결과가 마음에
들지 않을 때 Ctrl+Z 한 번으로 되돌릴 수 있어야 한다 — 컨테이너 하나, 이벤트
하나씩 스무 번 되돌리게 만들면 안 된다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from . import naming, source_location, plan as plan_mod
from .schema import SEP, GROUP_CONTAINERS, IMPORT_TO_QUERY
from .waapi_bridge import WwiseBridge, describe_error

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


@dataclass
class ImportResult:
    ok: bool = False
    imported: int = 0
    containers: int = 0
    events: list[str] = field(default_factory=list)
    switch_assignments: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def summary(self) -> str:
        if not self.ok:
            return f"임포트 실패: {self.error}"
        parts = [f"오디오 {self.imported}개"]
        if self.containers:
            parts.append(f"컨테이너 {self.containers}개")
        if self.events:
            parts.append(f"이벤트 {len(self.events)}개")
        if self.switch_assignments:
            parts.append(f"스위치 배정 {self.switch_assignments}개")
        # 구분자로 em dash 를 쓰지 않는다. 이 문자열은 콘솔(cp949)에도 나가는데
        # 거기서 인코딩 오류가 난다.
        return "완료: " + ", ".join(parts)


def apply(
    bridge: WwiseBridge,
    plan: plan_mod.Plan,
    *,
    import_operation: str = "useExisting",
    language: str = "SFX",
    event_root: str = "",
    switch_lookup: dict[str, dict] | None = None,
    progress: Progress | None = None,
) -> ImportResult:
    """계획을 실행한다.

    ``switch_lookup`` 은 ``{스위치그룹 경로: {"id":..., "children": {이름: id}}}``
    형태다. UI 가 이미 읽어 둔 것을 넘겨받아 여기서 다시 조회하지 않는다.
    """
    result = ImportResult()

    def say(message: str) -> None:
        """진행 상황 보고. 여기서 난 예외가 임포트를 되돌리면 안 된다.

        아래 try 블록은 모든 예외를 잡아 undo 그룹을 취소한다. 상태 표시줄
        갱신이나 콘솔 출력이 실패했다는 이유로 성공한 임포트를 통째로
        되돌리는 일은 없어야 한다.
        """
        if progress is None:
            return
        try:
            progress(message)
        except Exception:  # noqa: BLE001
            log.debug("진행 보고 실패", exc_info=True)

    if plan.has_errors:
        result.error = "계획에 오류가 있어 실행하지 않았습니다."
        return result
    if plan.is_empty:
        result.error = "임포트할 파일이 없습니다."
        return result

    # Audio-only updates preserve objects; a saved Switch/Sequence must never
    # be reported as a newly requested Random container merely because paths match.
    mismatch = (_container_type_conflict(bridge, plan)
                if import_operation != "createNew" else "")
    if mismatch:
        result.error = mismatch
        return result

    # 실패했을 때 되돌릴지 판단하려면 "이 그룹이 실제로 뭔가 바꿨는가" 를
    # 알아야 한다. 빈 undo 그룹에서 undo 를 부르면 Wwise 는 그 앞의 작업 —
    # 사용자가 손으로 하던 작업 — 을 되돌린다.
    before = _snapshot(bridge, plan.destination, event_root)

    bridge.begin_undo()
    try:
        say(f"오디오 {len(plan.imports)}개 임포트 중...")
        payload = plan_mod.payload(
            plan, import_operation=import_operation, language=language,
            existing_paths=before)
        response, warnings = (bridge.import_audio(payload) if payload["imports"]
                              else ({}, []))
        result.warnings.extend(warnings)
        result.containers = plan.container_count
        log.info("임포트 응답 오브젝트 %d개", len(response.get("objects", [])))

        # 응답을 믿지 않고 실제로 만들어졌는지 읽어서 센다. Wwise 는 임포트가
        # 부분적으로만 성공해도 정상 응답을 돌려주므로, 여기서 확인하지 않으면
        # 만들어지지 않은 것을 만들었다고 보고하게 된다.
        result.imported = _verify_created(bridge, plan, result)

        if plan.events:
            say(f"이벤트 {len(plan.events)}개 만드는 중...")
            _create_events(bridge, plan, event_root, result, say)

        if plan.switch_bindings:
            say("스위치 배정 중...")
            _assign_switches(bridge, plan, switch_lookup or {}, result, say)

        # Keep source provenance in the same undo group as the imported sound.
        for node in _iter_sound_nodes(plan.nodes):
            if import_operation == "useExisting" and node.path.lower() in before:
                continue  # useExisting kept the old audio; do not claim a new origin.
            try:
                if not source_location.remember(bridge, node.path, node.source, language):
                    result.warnings.append(f"'{node.name}': 원본 경로를 기록하지 못했습니다.")
            except Exception as exc:
                result.warnings.append(f"'{node.name}': 원본 경로 기록 실패 — {describe_error(exc)}")
        bridge.end_undo("Easy Sync 임포트")
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - 실패는 전부 되돌린다
        result.ok = False
        result.error = describe_error(exc)
        log.exception("임포트 실패")

        # 부분적으로 만들어진 오브젝트를 남기지 않는다. 반쯤 만들어진 계층은
        # 사용자가 손으로 치워야 하고, 무엇이 남았는지 알기도 어렵다.
        # 단, 정말로 뭔가 만들어졌을 때만 되돌린다 — 위 주석 참고.
        created = _snapshot(bridge, plan.destination, event_root) - before
        if created:
            if bridge.rollback_undo():
                result.warnings.append(
                    f"만들어진 {len(created)}개를 되돌렸습니다.")
            else:
                result.error += ("\n\n되돌리기에도 실패했습니다. "
                                 "Wwise 에서 Ctrl+Z 로 직접 되돌려 주세요.")
        else:
            # 아무것도 안 바뀌었으면 그룹만 닫는다. 여기서 undo 를 부르면
            # 사용자의 이전 작업이 사라진다.
            bridge.end_undo("Easy Sync (변경 없음)")

    say(result.summary())
    return result


def _container_type_conflict(bridge, plan: plan_mod.Plan) -> str:
    labels = dict(GROUP_CONTAINERS)
    def containers(nodes):
        for node in nodes:
            if node.source is None and node.type_token in labels:
                yield node
            yield from containers(node.children)
    for node in containers(plan.nodes):
        actual = bridge.object_at(node.path)
        if not actual:
            continue
        expected = IMPORT_TO_QUERY.get(node.type_token)
        actual_type = actual.get("type")
        actual_label = next((label for token, label in GROUP_CONTAINERS
                             if IMPORT_TO_QUERY.get(token) == actual_type), actual_type)
        mode_mismatch = False
        if actual_type == "RandomSequenceContainer":
            mode = actual.get("@RandomOrSequence")
            actual_label = "랜덤 컨테이너" if mode == 1 else "시퀀스 컨테이너"
            if node.type_token in ("Random Container", "Sequence Container"):
                mode_mismatch = mode != (1 if node.type_token == "Random Container" else 0)
        if actual_type != expected or mode_mismatch:
            return ("이미 있는 컨테이너와 선택한 종류가 다릅니다.\n\n"
                    f"{node.path}\n기존: {actual_label} / 선택: {labels[node.type_token]}\n\n"
                    "기존 종류에 맞춰 선택하거나, 새 컨테이너 이름을 지정하세요. "
                    "오디오 교체는 기존 컨테이너의 종류를 바꾸지 않습니다.")
    return ""


def _snapshot(bridge: WwiseBridge, destination: str, event_root: str) -> frozenset[str]:
    """이 작업이 건드릴 수 있는 영역의 현재 오브젝트 경로 집합.

    이벤트 쪽은 ``event_root`` 자체가 새로 만들어질 수 있으므로 한 단계 위를
    본다. 그래야 "폴더만 만들어지고 이벤트 생성에서 실패" 한 경우에도 변경을
    감지해 되돌릴 수 있다.
    """
    paths: set[str] = set(bridge.existing_paths(destination))
    if event_root:
        parent = event_root.rsplit(SEP, 1)[0]
        paths |= set(bridge.existing_paths(parent or event_root))
    return frozenset(paths)


def _verify_created(bridge: WwiseBridge, plan: plan_mod.Plan,
                    result: ImportResult) -> int:
    """계획한 Sound 가 실제로 Wwise 에 생겼는지 세어 본다.

    임포트 응답의 ``objects`` 배열은 "요청한 것" 에 가깝지 실제 생성 결과를
    보장하지 않는다. 목적지 하위를 다시 읽어 대조하는 편이 확실하다.
    """
    actual = bridge.existing_paths(plan.destination)
    made = 0
    missing: list[str] = []
    for node in _iter_sound_nodes(plan.nodes):
        if node.path.lower() in actual:
            made += 1
        else:
            missing.append(node.name)
    if missing:
        result.warnings.append(
            f"{len(missing)}개가 만들어지지 않았습니다: "
            + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else ""))
    return made


def _iter_sound_nodes(nodes: list[plan_mod.PlanNode]):
    for node in nodes:
        if node.source is not None:
            yield node
        yield from _iter_sound_nodes(node.children)


def _create_events(bridge: WwiseBridge, plan: plan_mod.Plan, event_root: str,
                   result: ImportResult, say: Progress) -> None:
    """계획된 이벤트를 만든다.

    이벤트는 **컨테이너를 가리킨다.** 임포트 호출의 ``event`` 필드를 쓰면
    Sound 하나하나를 가리키는 이벤트가 생기는데, 랜덤 컨테이너를 만든 목적이
    바로 그 하나하나를 감추는 것이므로 그러면 안 된다.
    """
    if not event_root:
        result.warnings.append("이벤트 경로가 지정되지 않아 이벤트를 만들지 않았습니다.")
        return

    # 이벤트 경로가 아직 없으면 폴더 체인부터 만든다.
    root_parts = [p for p in event_root.split(SEP) if p]
    if len(root_parts) < 2:
        result.warnings.append(
            f"이벤트 경로 '{event_root}' 가 너무 짧습니다. "
            f"Work Unit 아래를 지정하세요.")
        return

    existing = bridge.object_at(event_root)
    if existing:
        parent = existing["id"]
    else:
        # 첫 두 세그먼트(\Events\Work Unit)는 이미 있다고 보고 그 아래만 만든다.
        base = SEP + SEP.join(root_parts[:2])
        parent = bridge.ensure_folder_chain(base, root_parts[2:])

    for group, target_path in plan.events:
        target = bridge.object_at(target_path)
        if not target:
            result.warnings.append(
                f"이벤트 대상 '{target_path}' 를 찾지 못해 건너뜁니다.")
            continue
        name = naming.sanitized(group.resolved_event_name())
        # Reuse a matching event from the previous naming convention without
        # renaming IDs/names already referenced by game code or creating a duplicate.
        if not group.event_name and not bridge.object_at(event_root + SEP + name):
            legacy = bridge.object_at(event_root + SEP + "Play_" + name)
            if legacy and bridge.event_has_target(legacy["id"], target["id"]):
                result.events.append(legacy["name"])
                continue
        bridge.create_event(parent, name, target["id"])
        result.events.append(name)
        say(f"이벤트 {name}")


def _assign_switches(bridge: WwiseBridge, plan: plan_mod.Plan,
                     switch_lookup: dict[str, dict], result: ImportResult,
                     say: Progress) -> None:
    """스위치 컨테이너마다 그룹을 연결하고 자식을 배정한다.

    임포트 호출의 ``switchAssignation`` 필드는 2025.1.8 에서 조용히 아무것도
    하지 않는다(호출은 성공하고 배정만 비어 있다). 그래서 여기서 전용 API 로
    따로 처리한다.

    다중 단계면 컨테이너가 여러 겹이라 지시도 여러 개다. **바깥부터** 처리
    한다 — 안쪽 컨테이너는 바깥 컨테이너의 자식으로 배정되는데, 배정은
    바깥이 그룹을 이미 갖고 있어야 받아들여지기 때문이다.
    """
    for binding in sorted(plan.switch_bindings,
                          key=lambda b: b.container_path.count(SEP)):
        info = switch_lookup.get(binding.switch_group)
        if not info:
            result.warnings.append(
                f"스위치 그룹 '{binding.switch_group}' 을 찾지 못해 "
                f"'{binding.container_path}' 의 배정을 건너뜁니다.")
            continue
        container = bridge.object_at(binding.container_path)
        if not container:
            result.warnings.append(f"'{binding.container_path}' 를 찾지 못했습니다.")
            continue

        children = {c["name"].lower(): c["id"]
                    for c in bridge.children_of(container["id"])}
        switches = {name.lower(): sid for name, sid in info["children"].items()}

        assignments: list[tuple[str, str]] = []
        for child_name, switch_name in binding.children.items():
            child_id = children.get(child_name.lower())
            switch_id = switches.get(switch_name.lower())
            if child_id and switch_id:
                assignments.append((child_id, switch_id))
            else:
                result.warnings.append(
                    f"'{child_name}' -> '{switch_name}' 배정에 실패했습니다.")

        # 배정할 자식이 없어도 그룹 연결은 해 둔다. 계층만 만들어 두고 값은
        # 나중에 손으로 넣는 경우가 있고, 그룹이 붙어 있어야 그게 가능하다.
        bridge.assign_switches(container["id"], info["id"], assignments)
        result.switch_assignments += len(assignments)
        if assignments:
            say(f"{container.get('name', '')}: 스위치 {len(assignments)}개 배정")
