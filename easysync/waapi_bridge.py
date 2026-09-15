# -*- coding: utf-8 -*-
"""WAAPI 래퍼 — Easy Sync 가 쓰는 Wwise 호출만 얇게 감싼다.

여기 있는 호출은 전부 Wwise 2025.1.8(schema 133)에서 실제로 실행해 확인했다.
특히 다음 두 가지는 문서만 보고 짜면 조용히 틀리는 부분이라 주석으로 남긴다.

1. ``audio.import`` 의 ``switchAssignation`` 필드는 **동작하지 않는다.**
   호출은 성공하고 오브젝트도 만들어지지만 스위치 배정은 비어 있다.
   (``getAssignments`` 가 빈 배열, ``@@SwitchGroupOrStateGroup`` 이 널 GUID)
   그래서 스위치 배정은 ``object.setReference`` +
   ``switchContainer.addAssignment`` 로 따로 한다.

2. ``object.create`` 의 ``onNameConflict`` 는 **최상위에서만** 유효하다.
   ``children`` 안에 넣으면 ``Argument children/0/onNameConflict is unknown``
   으로 거부된다. 그래서 폴더 체인은 한 단계씩 만든다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import schema, transport
from .schema import SEP, Roots
from .transport import ConnectionFailed, WaapiError

log = logging.getLogger(__name__)

#: 트리 한 단계에서 받아올 필드.
#: ``parent`` 를 통째로 요청하면 ``{id, name}`` 만 오고 type 이 빠진다.
#: 점 표기로 쪼개 요청해야 type 까지 온다.
TREE_FIELDS = ["id", "name", "type", "path", "childrenCount", "@RandomOrSequence"]


def _path_query(path: str) -> str:
    # A filter returns no rows for a missing path. A direct from.path lookup
    # produces an error in Wwise's log even if the client catches the exception.
    safe = path.replace('"', '\\"')
    return f'$ where path = "{safe}"'


class WwiseUnavailable(Exception):
    """Wwise Authoring 에 닿지 못했을 때."""


class ImportRejected(Exception):
    """Wwise 가 임포트를 거부했을 때. 응답의 log 배열에서 읽어낸다."""


@dataclass
class ProjectInfo:
    name: str
    path: Path
    originals_root: Path
    roots: Roots
    languages: list[str] = field(default_factory=list)
    default_language: str = ""
    version: str = ""


def describe_error(exc: Exception) -> str:
    """WAAPI 예외를 작업자가 읽고 조치할 수 있는 문장으로 바꾼다.

    원본 예외 문자열은 WAMP 스택 덤프라서 사운드 디자이너에게 아무 의미가 없다.
    특히 모달 창 케이스는 실제로 자주 나고, 원인을 모르면 "툴이 멈췄다" 로만
    보인다.
    """
    # WaapiError 의 message 는 Wwise 가 실제로 한 말이라 그대로 쓸 수 있다.
    text = exc.message if isinstance(exc, WaapiError) else str(exc)
    lowered = text.lower()
    if "locked" in lowered or "modal" in lowered:
        return ("Wwise 에 열려 있는 대화상자 때문에 WAAPI 가 멈춰 있습니다.\n"
                "Wwise 로 가서 그 창을 닫고 다시 시도하세요.")
    if "not found" in lowered:
        return f"Wwise 에서 대상을 찾지 못했습니다.\n{text[:200]}"
    if "connect" in lowered or "refused" in lowered:
        return ("Wwise 에 연결하지 못했습니다.\n"
                "Wwise 가 실행 중인지, 프로젝트 설정 > Authoring API 가 "
                "켜져 있는지 확인하세요.")
    return text[:300]


class WwiseBridge:
    """Easy Sync 가 필요한 WAAPI 호출만 모아 둔 얇은 래퍼."""

    def __init__(self, url: str | None = None, *, allow_wamp: bool = True) -> None:
        try:
            self._transport = transport.connect(url, allow_wamp=allow_wamp)
        except ConnectionFailed as exc:
            raise WwiseUnavailable(str(exc)) from exc

    @property
    def transport_name(self) -> str:
        """지금 쓰는 전송 이름. 상태 표시줄에 보여 준다."""
        return getattr(self._transport, "name", "?")

    @property
    def busy(self) -> bool:
        return getattr(self._transport, "busy", False)

    @property
    def last_activity(self) -> float:
        return getattr(self._transport, "last_activity", 0.0)

    # -- 수명 주기 ---------------------------------------------------------
    def close(self) -> None:
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001 - 닫는 중 오류는 삼킨다
            pass

    def __enter__(self) -> "WwiseBridge":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _call(self, uri: str, args: dict | None = None) -> dict:
        return self._transport.call(uri, args or {}) or {}

    # -- 프로젝트 ----------------------------------------------------------
    def project_info(self) -> ProjectInfo:
        info = self._call("ak.wwise.core.getProjectInfo")
        dirs = info.get("directories") or {}
        languages = [l.get("name", "") for l in (info.get("languages") or [])]
        ref_id = info.get("referenceLanguageId")
        default_language = ""
        for lang in info.get("languages") or []:
            if lang.get("id") == ref_id:
                default_language = lang.get("name", "")
        return ProjectInfo(
            name=info.get("name", ""),
            path=Path(info.get("path", "")),
            originals_root=Path(dirs.get("originals", "")),
            roots=schema.resolve_roots(info),
            languages=languages,
            default_language=default_language or (languages[0] if languages else ""),
            version=info.get("displayTitle", ""),
        )

    def install_dir(self) -> str:
        """실행 중인 Wwise 의 설치 폴더. 아이콘을 여기서 읽는다."""
        info = self._call("ak.wwise.core.getInfo")
        return (info.get("directories") or {}).get("install", "")

    def is_dirty(self) -> bool:
        return bool(self._call("ak.wwise.core.getProjectInfo").get("isDirty"))

    def save(self) -> None:
        self._call("ak.wwise.core.project.save")

    # -- 계층 조회 ---------------------------------------------------------
    def children_of(self, parent: str) -> list[dict]:
        """한 단계 자식만 가져온다.

        전체 계층을 한 번에 읽지 않는 이유: 실제 프로젝트의 오디오 탭은
        수만 개 오브젝트가 될 수 있다. 펼칠 때마다 한 단계씩 읽으면 창이
        즉시 뜨고, 사용자가 실제로 보는 부분만 비용을 낸다.
        """
        args = ({"waql": _path_query(parent) + " select children"}
                if parent.startswith(SEP) else {
                    "from": {"id": [parent]},
                    "transform": [{"select": ["children"]}],
                })
        result = self._call("ak.wwise.core.object.get", {
            **args, "options": {"return": TREE_FIELDS}})
        return result.get("return", [])

    def object_at(self, path_or_id: str) -> dict | None:
        """오브젝트 하나를 가져온다. 없으면 None.

        경로는 필터로 조회해 없는 경로도 Wwise 오류 로그를 남기지 않는다.
        """
        key = "path" if path_or_id.startswith(SEP) else "id"
        source = ({"waql": _path_query(path_or_id)} if key == "path"
                  else {"from": {"id": [path_or_id]}})
        try:
            result = self._call("ak.wwise.core.object.get", {
                **source,
                "options": {"return": TREE_FIELDS},
            })
        except WaapiError as exc:
            if "cannot be resolved" in str(exc) or "not found" in str(exc).lower():
                return None
            raise
        rows = result.get("return", [])
        return rows[0] if rows else None

    def path_segments(self, path: str) -> list[tuple[str, str]]:
        """경로를 (이름, 타입) 목록으로 편다. 계층 루트는 뺀다.

        ``\\Containers\\Audio\\NPC\\Creature_Voice`` 에 대해
        ``[("Audio","WorkUnit"), ("NPC","Folder"),
        ("Creature_Voice","PropertyContainer")]`` 를 돌려준다.

        Originals 하위 경로를 계층에 맞춰 만들 때 쓴다. 세그먼트마다 타입을
        알아야 "폴더는 폴더로 만들고 랜덤 컨테이너는 만들지 않는다" 를
        판단할 수 있다.

        루트(``\\Containers``)를 타입으로 걸러내지 않고 **위치로** 뺀다.
        루트 자신도 ``WorkUnit`` 으로 보고되기 때문에(실측) 타입으로 거르면
        진짜 Work Unit 까지 같이 빠진다.
        """
        target = self.object_at(path)
        if not target:
            return []
        rows = self._call("ak.wwise.core.object.get", {
            "from": {"id": [target["id"]]},
            "transform": [{"select": ["ancestors"]}],
            "options": {"return": ["name", "type", "path"]},
        }).get("return", [])
        # ancestors 는 가까운 조상부터 루트 순으로 온다. 뒤집어 위에서 아래로.
        chain = [(r.get("name", ""), r.get("type", ""), r.get("path", ""))
                 for r in reversed(rows)]
        chain.append((target.get("name", ""), target.get("type", ""),
                      target.get("path", "")))
        # 첫 항목이 계층 루트다. 경로 세그먼트가 하나뿐인 것으로도 확인된다.
        return [(name, kind) for name, kind, full in chain
                if len([p for p in full.split(SEP) if p]) > 1]

    def search(self, term: str, under: str = "", limit: int = 300) -> list[dict]:
        """이름으로 오브젝트를 찾는다. ``under`` 가 있으면 그 하위로 제한한다."""
        safe = term.replace('"', '\\"')
        query = f'$ from search "{safe}"'
        if under:
            query = f'$ "{under}" select descendants where name : "{safe}"'
        result = self._call("ak.wwise.core.object.get", {
            "waql": query,
            "options": {"return": TREE_FIELDS},
        })
        return result.get("return", [])[:limit]

    def existing_paths(self, destination: str) -> frozenset[str]:
        """목적지 아래에 이미 있는 모든 오브젝트 경로를 소문자로 돌려준다.

        미리보기에서 "새로 만들어짐 / 이미 있음" 을 구분하는 데 쓴다.

        "이 경로들이 있느냐" 고 목록으로 묻지 않는 이유: WAQL 의
        ``$ "a", "b"`` 형태는 하나라도 없으면 **전체가** ``Object not found``
        로 실패한다. 그런데 우리가 확인하려는 경로는 대부분 아직 없는
        경로다(그래서 만들려는 것이다). 목적지 하위를 통째로 한 번 읽어
        비교하는 쪽이 호출도 한 번이고 실패 경로도 없다.

        대소문자를 낮춰 담는 이유: Wwise 는 이름의 대소문자를 보존하지만
        대소문자만 다른 형제는 금지한다. ``Hero`` 와 ``HERO`` 를 서로 다른
        것으로 보면 "괜찮다" 고 판정한 뒤 실제 임포트에서 충돌한다.
        """
        if not destination:
            return frozenset()
        safe = destination.replace('"', '\\"')
        try:
            result = self._call("ak.wwise.core.object.get", {
                "waql": f'$ "{safe}" select descendants',
                "options": {"return": ["path"]},
            })
        except WaapiError as exc:
            log.debug("목적지 하위 조회 실패 (%s): %s", destination, exc)
            return frozenset()
        return frozenset(
            (row.get("path") or "").lower() for row in result.get("return", []))

    def switch_groups(self) -> list[dict]:
        '''스위치/스테이트 그룹을 값까지 함께 가져온다.

        그룹마다 자식을 따로 묻지 않는다. 그룹이 수십 개인 프로젝트에서
        그러면 호출이 수십 번 나가고, 그 사이 창은 스위치 칸을 비운 채
        기다린다. 값을 **한 번에** 읽고 부모 id 로 나눠 담는다 — 그룹
        수와 상관없이 호출은 네 번이다.
        '''
        out: list[dict] = []
        for group_type, value_type in (("SwitchGroup", "Switch"),
                                       ("StateGroup", "State")):
            try:
                groups = self._call("ak.wwise.core.object.get", {
                    "waql": f"$ from type {group_type}",
                    "options": {"return": ["id", "name", "path", "type"]},
                }).get("return", [])
                if not groups:
                    continue
                values = self._call("ak.wwise.core.object.get", {
                    "waql": f"$ from type {value_type}",
                    "options": {"return": ["id", "name", "type", "parent"]},
                }).get("return", [])
            except Exception as exc:  # noqa: BLE001
                log.warning("%s 조회 실패: %s", group_type, exc)
                continue

            by_parent: dict[str, list[dict]] = {}
            for value in values:
                parent = value.get("parent") or {}
                by_parent.setdefault(parent.get("id", ""), []).append(value)
            for group in groups:
                group["children"] = by_parent.get(group["id"], [])
                out.append(group)
        return out

    def events(self) -> list[dict]:
        """이벤트 전체를 한 번에 가져온다.

        오디오 탭과 달리 이벤트는 수가 적고 즉시 검색되어야 해서 전부 읽는다.
        """
        result = self._call("ak.wwise.core.object.get", {
            "waql": "$ from type Event",
            "options": {"return": ["id", "name", "path"]},
        })
        return result.get("return", [])

    # -- 쓰기 --------------------------------------------------------------
    def import_audio(self, args: dict) -> tuple[dict, list[str]]:
        """``ak.wwise.core.audio.import`` 호출. (응답, 경고 목록) 을 돌려준다.

        ``objectPath`` 의 ``<타입>이름`` 토큰이 중간 컨테이너를 알아서
        만들어 준다. 그래서 컨테이너를 따로 ``object.create`` 할 필요가 없다.

        **이 호출은 실패해도 예외를 던지지 않는다.** 없는 오디오 파일, 잘못된
        타입 토큰, 잘못된 루트 경로 — 전부 정상 응답으로 돌아온다(실측).
        실제 결과는 응답의 ``log`` 배열에만 들어 있다:

            severity="Error"   -> 아무것도 만들어지지 않았다
            severity="Warning" -> 만들어졌지만 문제가 있다
                                  (예: 파일을 못 찾아 빈 소스로 생성)

        그래서 여기서 ``log`` 를 읽어 Error 는 예외로 올리고 Warning 은
        호출자에게 돌려준다. 이걸 하지 않으면 아무것도 만들어지지 않았는데
        "완료" 라고 보고하게 된다.
        """
        response = self._call("ak.wwise.core.audio.import", args)
        errors: list[str] = []
        warnings: list[str] = []
        for entry in response.get("log") or []:
            message = entry.get("message", "")
            if entry.get("severity") == "Error":
                errors.append(message)
            else:
                warnings.append(message)
        if errors:
            raise ImportRejected("\n".join(errors))
        return response, warnings

    def ensure_folder_chain(self, root: str, segments: list[str],
                            folder_type: str = "Folder") -> str:
        """``root`` 아래에 폴더 체인을 만들고 마지막 폴더의 id 를 돌려준다.

        한 단계씩 만드는 이유는 파일 맨 위 주석에 있다 — ``onNameConflict``
        가 ``children`` 안에서는 거부되기 때문에 중첩 생성으로는 "있으면
        재사용" 을 표현할 수 없다.
        """
        current = root
        for segment in segments:
            if not segment:
                continue
            result = self._call("ak.wwise.core.object.create", {
                "parent": current,
                "type": folder_type,
                "name": segment,
                "onNameConflict": "merge",
            })
            current = result.get("id") or (current + SEP + segment)
        return current

    def event_has_target(self, event_id: str, target_id: str) -> bool:
        rows = self._call("ak.wwise.core.object.get", {
            "from": {"id": [event_id]}, "transform": [{"select": ["children"]}],
            "options": {"return": ["type", "@ActionType", "@Target"]},
        }).get("return", [])
        return any(row.get("type") == "Action"
                   and row.get("@ActionType") == schema.ACTION_TYPE_PLAY
                   and (row.get("@Target") or {}).get("id") == target_id for row in rows)

    def create_event(self, parent: str, name: str, target_id: str) -> dict:
        """대상 오브젝트를 재생하는 이벤트를 만든다.

        ``merge`` 라서 같은 이름의 이벤트가 이미 있으면 재사용되고, 같은
        대상을 가리키는 Play 액션이 이미 있으면 중복 생성되지 않는다(실측).
        """
        return self._call("ak.wwise.core.object.create", {
            "parent": parent,
            "type": "Event",
            "name": name,
            "onNameConflict": "merge",
            "children": [{
                "type": "Action",
                "name": "",
                "@ActionType": schema.ACTION_TYPE_PLAY,
                "@Target": target_id,
            }],
        })

    def assign_switches(self, container_id: str, group_id: str,
                        assignments: list[tuple[str, str]]) -> None:
        """스위치 컨테이너에 그룹을 연결하고 자식을 배정한다.

        ``assignments`` 는 (자식 id, 스위치/스테이트 id) 목록이다.
        """
        self._call("ak.wwise.core.object.setReference", {
            "object": container_id,
            "reference": "SwitchGroupOrStateGroup",
            "value": group_id,
        })
        for child_id, switch_id in assignments:
            self._call("ak.wwise.core.switchContainer.addAssignment", {
                "child": child_id,
                "stateOrSwitch": switch_id,
            })

    # -- UI 연동 -----------------------------------------------------------
    def selected_objects(self) -> list[dict]:
        result = self._call("ak.wwise.ui.getSelectedObjects", {
            "options": {"return": TREE_FIELDS},
        })
        return result.get("return", [])

    def selected_paths(self) -> list[tuple[str, str]]:
        """Wwise 에서 지금 고른 것들의 (경로, 타입).

        Wwise 안에서 단축키로 띄웠을 때 "어디에 넣을지" 를 이미 골라 둔
        상태이므로, 그 선택을 그대로 가져와 채운다.
        """
        rows = self.selected_objects()
        return [(r.get("path", ""), r.get("type", "")) for r in rows
                if r.get("path")]

    def reveal(self, object_id: str) -> None:
        """Wwise 를 앞으로 가져와 해당 오브젝트를 선택한다."""
        try:
            self._call("ak.wwise.ui.bringToForeground")
            self._call("ak.wwise.ui.commands.execute", {
                "command": "FindInProjectExplorerSelectionChannel1",
                "objects": [object_id],
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("reveal 실패: %s", exc)

    # -- 실행 취소 ---------------------------------------------------------
    def begin_undo(self) -> None:
        self._call("ak.wwise.core.undo.beginGroup")

    def end_undo(self, display_name: str) -> None:
        """undo 그룹을 닫는다. 이후 Ctrl+Z 한 번이 그룹 전체를 되돌린다(실측)."""
        self._call("ak.wwise.core.undo.endGroup", {"displayName": display_name})

    def rollback_undo(self, display_name: str = "Easy Sync (취소됨)") -> bool:
        """열려 있는 undo 그룹을 닫고 그 안의 작업을 되돌린다.

        **부른 쪽이 그룹 안에서 실제로 뭔가 바뀌었음을 확인한 뒤에만 부를 것.**
        빈 그룹에서 부르면 Wwise 는 그 앞의 작업을 되돌린다 — 즉 사용자가
        Easy Sync 를 켜기 전에 손으로 한 작업이 사라진다(실측 확인). 아무것도
        바뀌지 않았다면 ``end_undo`` 만 부르면 된다.

        ``ak.wwise.core.undo.cancelGroup`` 을 쓰지 않는 이유: 2025.1.8 에서
        cancelGroup 은 그룹만 닫고 **오브젝트를 되돌리지 않는다**(실측 —
        취소 후에도 만들어진 컨테이너가 그대로 남았다).
        """
        try:
            self._call("ak.wwise.core.undo.endGroup", {"displayName": display_name})
            self._call("ak.wwise.core.undo.undo")
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("되돌리기 실패: %s", exc)
            return False


def ping(url: str | None = None) -> tuple[bool, str]:
    """Wwise 가 응답하는지 짧게 확인한다.

    긴 조회를 던지기 전에 부른다. 모달 창에 막혀 있으면 30초 타임아웃을
    기다리는 대신 여기서 바로 알 수 있다.
    """
    try:
        link = transport.connect(url)
    except ConnectionFailed:
        return False, "Wwise 가 실행 중이 아니거나 Authoring API 가 꺼져 있습니다."
    try:
        info = link.call("ak.wwise.core.getInfo") or {}
        version = (info.get("version") or {}).get("displayName", "")
        return True, f"Wwise {version} ({link.name})"
    except Exception as exc:  # noqa: BLE001
        return False, describe_error(exc)
    finally:
        link.close()
