# -*- coding: utf-8 -*-
"""Easy Sync 메인 창.

두 칸으로 나뉜다.

  왼쪽   위치 선택. 오디오 탭에서 임포트할 곳을, 이벤트 탭에서 이벤트를 만들
         곳을 고른다. 두 탭 모두 검색과 핀을 쓸 수 있다.
  오른쪽 파일과 묶음. 여기서 컨테이너 종류와 이벤트 여부를 정하고, **같은
         트리에서** 무엇이 새로 만들어지고 무엇이 이미 있는지 바로 본다.

미리보기를 따로 두지 않는 이유: 편집하는 곳과 결과를 보는 곳이 떨어져 있으면
눈이 좌우로 왔다 갔다 해야 한다. 묶음 트리의 '상태' 열이 곧 미리보기다.
그래도 계획 자체는 ``plan.Plan`` 하나에서 나오므로 화면과 실행이 어긋나지
않는다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import (icons, importer, instances, naming, options_dialog,
               plan as plan_mod, schema, suggest)
from .path_display import PathDisplay
from .link import WwiseLink
from .options_dialog import OptionsDialog
from .settings import Settings
from .tasks import TaskRunner
from .waapi_bridge import ProjectInfo, WwiseBridge, describe_error

log = logging.getLogger(__name__)

AUDIO_SUFFIXES = {".wav", ".aif", ".aiff", ".flac", ".ogg"}

STATUS_COLOR = {
    plan_mod.NEW: QColor(90, 200, 110),
    plan_mod.EXISTING: QColor(140, 140, 140),
    plan_mod.REPLACE: QColor(230, 160, 60),
    plan_mod.RENAME: QColor(100, 160, 240),
}
STATUS_LABEL = {
    plan_mod.NEW: "새로 만듦",
    plan_mod.EXISTING: "이미 있음",
    plan_mod.REPLACE: "오디오 교체",
    plan_mod.RENAME: "이름 변경",
}
STATUS_TOOLTIP = {
    plan_mod.NEW: "Wwise 에 없어서 새로 만들어집니다.",
    plan_mod.EXISTING: "이미 있습니다. 그대로 두고 오디오도 다시 넣지 않습니다.",
    plan_mod.REPLACE: "이미 있습니다. 오디오 소스를 새 파일로 교체합니다.",
    plan_mod.RENAME: "이미 있어서 _01 처럼 이름을 바꿔 새로 만듭니다.",
}

IMPORT_OPERATIONS = [
    ("useExisting", "이미 있으면 그대로 둠"),
    ("replaceExisting", "이미 있으면 오디오 교체"),
    ("createNew", "항상 새로 만듦 (_01 붙음)"),
]

ROLE_NODE = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_LOADED = Qt.ItemDataRole.UserRole + 2
#: 줄이 속한 묶음. 낱개 줄에도 달려 있어서 이벤트·컨테이너
#: 지정을 줄 종류와 상관없이 같은 방식으로 다룰 수 있다.
ROLE_GROUP = Qt.ItemDataRole.UserRole + 3

KIND_GROUP = "group"
KIND_FILE = "file"

#: 임포트 대상으로 고른 항목을 칠하는 색. 포커스로 생기는 파란 선택색과
#: 구분되어야 한다 — 고른 위치는 포커스가 딴 데로 가도 계속 보여야 한다.
CHOSEN_BG = QColor(38, 92, 58)
CHOSEN_FG = QColor(225, 245, 230)


def _iter_sounds(nodes: list[plan_mod.PlanNode]):
    for node in nodes:
        if node.source is not None:
            yield node
        yield from _iter_sounds(node.children)


class ContainerComboBox(QComboBox):
    """Scrolling the file list must not silently change a container type."""
    def wheelEvent(self, event) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


# ---------------------------------------------------------------------------
# 계층 트리 한 칸 (오디오 / 이벤트 공용)
# ---------------------------------------------------------------------------
class HierarchyPanel(QWidget):
    """Wwise 계층 하나를 보여 주고 그중 하나를 고르게 한다.

    오디오 탭과 이벤트 탭이 하는 일이 똑같아서 한 클래스로 쓴다 — 검색,
    핀 필터, 펼칠 때 한 단계씩 읽기, 고른 항목 표시.
    """

    chosen = Signal(str)          # 고른 오브젝트의 경로
    failed = Signal(object)       # 예외 객체
    pins_changed = Signal()
    pin_unavailable = Signal(str)

    def __init__(self, tasks: TaskRunner, allowed_types: frozenset[str],
                 hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tasks = tasks
        # Wwise 에 붙기 전에도 창은 떠야 하므로 bridge 는 나중에 들어온다.
        self.bridge: WwiseBridge | None = None
        self.root = ""
        self.allowed_types = allowed_types
        self._chosen_item: QTreeWidgetItem | None = None
        self._pending_path = ""
        self._revision = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("찾기 (Enter)")
        self.search.returnPressed.connect(self._search)
        row.addWidget(self.search, 1)
        pin_button = QPushButton("핀 고정")
        pin_button.setToolTip(
            "고른 경로를 현재 Wwise 프로젝트의 핀으로 저장합니다.\n"
            "핀을 걸면 그 하위만 보여서 큰 프로젝트에서\n"
            "자기 작업 영역만 볼 수 있습니다.")
        pin_button.clicked.connect(self._add_pin)
        row.addWidget(pin_button)
        self.unpin_button = QPushButton("핀 해제")
        self.unpin_button.setToolTip(
            "지금 걸려 있는 핀을 목록에서 지우고 전체 보기로 돌아갑니다.")
        self.unpin_button.clicked.connect(self._remove_current_pin)
        self.unpin_button.setEnabled(False)
        row.addWidget(self.unpin_button)
        layout.addLayout(row)

        self.pin_box = QComboBox()
        self.pin_box.addItem("핀 없음 (전체 보기)", "")
        self.pin_box.setToolTip("현재 Wwise 프로젝트에 저장한 핀 중에서 고릅니다.")
        self.pin_box.currentIndexChanged.connect(self._apply_pin)
        layout.addWidget(self.pin_box)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(self.tree.iconSize().expandedTo(
            self.tree.iconSize().__class__(18, 18)))
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.tree, 1)

        self.hint = QLabel(hint)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #8a8a8a;")
        layout.addWidget(self.hint)

    # -- 공개 API ----------------------------------------------------------
    @property
    def pins(self) -> list[str]:
        return [self.pin_box.itemData(i) for i in range(1, self.pin_box.count())]

    def set_pins(self, pins: list[str]) -> None:
        """프로젝트 전환 중 이전 연결로 조회하지 않고 목록만 교체한다."""
        blocked = self.pin_box.blockSignals(True)
        try:
            self.pin_box.clear()
            self.pin_box.addItem("핀 없음 (전체 보기)", "")
            for pin in pins:
                if pin and self.pin_box.findData(pin) < 0:
                    self.pin_box.addItem(self._short(pin), pin)
            self.pin_box.setCurrentIndex(0)
        finally:
            self.pin_box.blockSignals(blocked)
        self.unpin_button.setEnabled(False)
        self.search.clear()

    def set_source(self, bridge: WwiseBridge | None, root: str) -> None:
        """Wwise 에 붙었을 때(또는 끊겼을 때) 알려 준다."""
        self._revision += 1
        self.bridge = bridge
        self.root = root
        self.setEnabled(bridge is not None)
        if bridge is None:
            self.tree.clear()
            self._chosen_item = None

    def reload(self, select_path: str = "") -> None:
        """트리를 처음부터 다시 읽는다. ``select_path`` 가 있으면 찾아서 고른다."""
        self._revision += 1
        revision = self._revision
        self._pending_path = select_path
        self.tree.clear()
        self._chosen_item = None
        if self.bridge is None or not self.root:
            return          # 아직 Wwise 에 붙지 않았다
        pin = self.pin_box.currentData() or ""
        base = pin or self.root
        root = self.root
        bridge = self.bridge
        def fetch():
            root_row = bridge.object_at(pin) if pin else None
            missing = bool(pin and root_row is None)
            actual_base = root if missing else base
            return bridge.children_of(actual_base), root_row, actual_base, missing
        def done(result):
            rows, root_row, actual_base, missing = result
            if missing:
                self.set_pins(self.pins)
                self._pending_path = ""
                self.pin_unavailable.emit(pin)
            self._fill_top(rows, actual_base, root_row)
            if missing:
                self.hint.setText("핀 경로가 없어 전체 보기로 전환했습니다. 현재 위치를 다시 선택하세요.")
        self.tasks.run(fetch,
                       on_done=lambda result: self._if_current(
                           revision, done, result),
                       on_fail=lambda exc: self._if_current(revision, self.failed.emit, exc))

    def _if_current(self, revision, callback, *args):
        if revision == self._revision:
            callback(*args)

    @staticmethod
    def _short(path: str) -> str:
        parts = [p for p in path.split(schema.SEP) if p]
        return parts[-1] if parts else path

    def _fill_top(self, rows: list[dict], base: str, root_row=None) -> None:
        parent = self.tree
        if root_row:
            parent = self._make_item(self.tree, root_row)
            parent.setData(0, ROLE_LOADED, True)
            parent.takeChildren()
        for row in rows:
            self._make_item(parent, row)
        if isinstance(parent, QTreeWidgetItem):
            parent.setExpanded(True)
        self._advance_toward_pending()

    def _make_item(self, parent, row: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [row.get("name", "")])
        item.setIcon(0, icons.for_object(row))
        item.setData(0, ROLE_NODE, row)
        item.setData(0, ROLE_LOADED, False)
        item.setToolTip(0, f'{row.get("path", "")}\n{row.get("type", "")}')
        if (row.get("childrenCount") or 0) > 0:
            QTreeWidgetItem(item, ["..."])
        if row.get("type") not in self.allowed_types:
            item.setForeground(0, QBrush(QColor(130, 130, 130)))
        return item

    def _expand(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_LOADED):
            return
        row = item.data(0, ROLE_NODE)
        if not row:
            return
        item.setData(0, ROLE_LOADED, True)
        revision = self._revision
        def failed(exc):
            if revision == self._revision:
                item.setData(0, ROLE_LOADED, False)
                self.failed.emit(exc)
        self.tasks.run(self.bridge.children_of, row["id"],
                       on_done=lambda rows, it=item: self._if_current(
                           revision, self._fill_children, it, rows),
                       on_fail=failed)

    def _fill_children(self, item: QTreeWidgetItem, rows: list[dict]) -> None:
        item.takeChildren()
        for row in rows:
            self._make_item(item, row)
        self._advance_toward_pending()

    def _advance_toward_pending(self) -> None:
        """지난번에 고른 경로를 한 단계씩 펼쳐 가며 찾아낸다.

        트리는 펼칠 때마다 한 단계씩만 읽으므로, 저장된 경로가 깊으면 그
        경로는 아직 트리에 없다. 조상 중 가장 깊이 로드된 것을 펼치고, 자식이
        도착하면 (``_fill_children`` 이 다시 여기를 불러) 다음 단계로 간다.
        """
        pending = self._pending_path
        if not pending:
            return
        if self._select_path(pending):
            return

        best: QTreeWidgetItem | None = None
        best_depth = 0

        def walk(item: QTreeWidgetItem) -> None:
            nonlocal best, best_depth
            row = item.data(0, ROLE_NODE) or {}
            path = row.get("path", "")
            # 경로 문자열이 접두라도 세그먼트 경계에서 끊겨야 조상이다.
            # 그러지 않으면 \A\VOICE 가 \A\VOICEOVER 의 조상으로 잡힌다.
            if path and pending.startswith(path + schema.SEP):
                depth = len(path)
                if depth > best_depth:
                    best, best_depth = item, depth
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

        if best is None:
            self._pending_path = ""      # 지워졌거나 핀 범위 밖이다
            return
        if best.data(0, ROLE_LOADED):
            # 이미 읽었는데도 없다면 그 경로는 더 이상 존재하지 않는다.
            self._pending_path = ""
            return
        best.setExpanded(True)           # itemExpanded -> _expand -> 다음 단계

    def _selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        row = items[0].data(0, ROLE_NODE)
        if not row or row.get("type") not in self.allowed_types:
            return
        self._mark(items[0])
        self.chosen.emit(row.get("path", ""))

    def _mark(self, item: QTreeWidgetItem) -> None:
        """고른 항목에 색을 입힌다.

        포커스 선택색(파란색)은 포커스가 딴 위젯으로 가면 흐려진다. 임포트가
        어디로 가는지는 항상 보여야 하므로 배경을 직접 칠한다.
        """
        if self._chosen_item is not None:
            try:
                self._chosen_item.setBackground(0, QBrush())
                self._chosen_item.setForeground(0, QBrush())
                font = self._chosen_item.font(0)
                font.setBold(False)
                self._chosen_item.setFont(0, font)
            except RuntimeError:
                pass  # 트리를 다시 그리면서 사라진 항목
        item.setBackground(0, QBrush(CHOSEN_BG))
        item.setForeground(0, QBrush(CHOSEN_FG))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self._chosen_item = item

    def _select_path(self, path: str) -> bool:
        def walk(item: QTreeWidgetItem) -> bool:
            row = item.data(0, ROLE_NODE)
            if row and row.get("path") == path:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                self._pending_path = ""
                return True
            return any(walk(item.child(i)) for i in range(item.childCount()))

        for i in range(self.tree.topLevelItemCount()):
            if walk(self.tree.topLevelItem(i)):
                return True
        return False

    def _search(self) -> None:
        term = self.search.text().strip()
        if not term:
            self.reload()
            return
        pin = self.pin_box.currentData() or ""
        if self.bridge is None:
            return
        self._revision += 1
        revision = self._revision
        self.tasks.run(self.bridge.search, term, pin or self.root,
                       on_done=lambda rows: self._if_current(revision, self._fill_search, rows),
                       on_fail=lambda exc: self._if_current(revision, self.failed.emit, exc))

    def _fill_search(self, rows: list[dict]) -> None:
        self._revision += 1
        self.tree.clear()
        self._chosen_item = None
        for row in rows:
            self._make_item(self.tree, row)
        self.hint.setText(f"검색 결과 {len(rows)}개 — 검색어를 지우고 Enter 로 복귀")

    def _add_pin(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        path = (items[0].data(0, ROLE_NODE) or {}).get("path", "")
        if not path:
            return
        if self.pin_box.findData(path) < 0:
            self.pin_box.addItem(self._short(path), path)
            self.pins_changed.emit()
        self.pin_box.setCurrentIndex(self.pin_box.findData(path))

    def _remove_current_pin(self) -> None:
        self._remove_pin(self.pin_box.currentData())

    def _remove_pin(self, path: str) -> None:
        index = self.pin_box.findData(path)
        if index <= 0:
            return
        active = self.pin_box.currentData()
        self.set_pins([pin for pin in self.pins if pin != path])
        if active and active != path:
            self.pin_box.setCurrentIndex(self.pin_box.findData(active))
        else:
            self.reload()
        self.pins_changed.emit()

    def _apply_pin(self) -> None:
        self.unpin_button.setEnabled(bool(self.pin_box.currentData()))
        self.search.clear()
        self.reload()

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        row = item.data(0, ROLE_NODE) or {}
        menu = QMenu(self)
        reveal = QAction("Wwise 에서 보기", self)
        reveal.triggered.connect(lambda: self.bridge.reveal(row.get("id", "")))
        menu.addAction(reveal)
        path = row.get("path", "")
        if path and self.pin_box.findData(path) > 0:
            unpin = QAction("이 경로를 핀에서 제거", self)
            unpin.triggered.connect(
                lambda: self._remove_pin(path))
            menu.addAction(unpin)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---------------------------------------------------------------------------
# 메인 창
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    #: 탐색기에서 뒤늦게 도착한 파일. 소켓 스레드가 emit 하고 Qt 가 UI
    #: 스레드로 넘겨 준다 — 위젯은 항상 UI 스레드에서만 건드린다.
    files_received = Signal(list)

    def __init__(self, link: WwiseLink, settings: Settings,
                 initial_files: list[Path] | None = None) -> None:
        super().__init__()
        self.link = link
        self.settings = settings
        self.tasks = TaskRunner()
        self.groups: list[plan_mod.Group] = []
        self.plan: plan_mod.Plan | None = None
        self.destination = ""
        self.event_root = ""
        self._switch_lookup: dict[str, dict] = {}
        self._existing_cache: frozenset[str] = frozenset()
        self._dest_segments: list[tuple[str, str]] = []
        self._suggestion: str | None = None
        self._adopted_selection = False
        self._last_project_path = None
        self._pin_project_key: str | None = None
        self._destination_revision = 0
        self._destination_loading = False
        self._importing = False

        # Wwise 에 붙기 전에도 창은 떠야 한다. 프로젝트 정보가 없는 동안은
        # 기본 루트 이름으로 버틴다 — 붙으면 진짜 값으로 갈아 끼운다.
        self.project: ProjectInfo | None = None
        self.roots = schema.Roots()

        self.setWindowTitle("Easy Sync")
        self.resize(1660, 1000)
        self.setAcceptDrops(True)

        self._build_ui()
        self.audio_panel.pins_changed.connect(self._save_project_pins)
        self.event_panel.pins_changed.connect(self._save_project_pins)
        self.audio_panel.pin_unavailable.connect(
            lambda path: self._on_pin_unavailable(self.audio_panel, path))
        self.event_panel.pin_unavailable.connect(
            lambda path: self._on_pin_unavailable(self.event_panel, path))

        # 타이머를 설정 복원보다 먼저 만든다. 복원이 체크박스를 건드리면
        # stateChanged 가 곧바로 _queue_replan 을 부르기 때문이다.
        self._replan_timer = QTimer(self)
        self._replan_timer.setSingleShot(True)
        self._replan_timer.setInterval(220)
        self._replan_timer.timeout.connect(self._rebuild_plan)

        # 추천은 단어마다 WAAPI 검색이 나가므로 편집할 때마다 돌면 안 된다.
        # 계획 재계산과 같은 방식으로 잠깐 모았다 한 번만 돈다.
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(600)
        self._suggest_timer.timeout.connect(self._refresh_suggestion)

        self._destination_timer = QTimer(self)
        self._destination_timer.setSingleShot(True)
        self._destination_timer.setInterval(150)
        self._destination_timer.timeout.connect(self._fetch_destination)
        self._incoming_paths: list[Path] = []
        self._incoming_timer = QTimer(self)
        self._incoming_timer.setSingleShot(True)
        self._incoming_timer.setInterval(180)
        self._incoming_timer.timeout.connect(self._flush_incoming_files)
        self._restore_settings()

        link.connected.connect(self._on_wwise_connected)
        link.lost.connect(self._on_wwise_lost)
        link.status.connect(self._set_connection_status)
        # 이미 붙어 있는 링크를 받았을 수도 있다. 그러면 connected 신호는
        # 창이 생기기 전에 지나갔으므로 지금 상태를 직접 읽어 맞춘다.
        if link.is_connected and link.project is not None:
            self._on_wwise_connected(link.project)
        else:
            self._set_connection_status("Wwise 를 찾는 중...")

        self.files_received.connect(self._on_files_received)
        if initial_files:
            self.add_files(initial_files)

    # -- 화면 구성 ---------------------------------------------------------
    def _build_ui(self) -> None:
        self._build_menu()
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(self._build_header())

        # 세 칸. 오디오 위치 · 이벤트 위치 · 파일과 묶음.
        # 예전에는 오디오와 이벤트가 한 칸 안의 탭이었는데, 그러면 둘을
        # 동시에 볼 수 없어서 "어디에 넣고 이벤트는 어디에 만드는지" 를
        # 탭을 오가며 확인해야 했다. 파일 칸은 그만큼 줄여도 넉넉하다.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for panel, stretch, minimum in (
            (self._build_audio_panel(), 2, 280),
            (self._build_event_panel(), 2, 280),
            (self._build_work_panel(), 4, 560),
        ):
            panel.setMinimumWidth(minimum)
            splitter.addWidget(panel)
            splitter.setStretchFactor(splitter.count() - 1, stretch)
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_footer())

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("파일(&F)")
        for text, slot, tip, shortcut in (
            ("파일 추가...", self._pick_files, "임포트할 오디오 파일을 고릅니다.", "Ctrl+O"),
            ("목록 비우기", self._clear_files, "가져온 파일 목록을 비웁니다.", ""),
            ("Wwise 다시 읽기", self._reload_all, "계층과 스위치 그룹을 다시 읽습니다.", "F5"),
        ):
            action = QAction(text, self)
            action.setStatusTip(tip)
            action.setToolTip(tip)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("닫기", self)
        quit_action.setShortcut("Ctrl+W")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        options_menu = bar.addMenu("옵션(&O)")
        open_options = QAction("옵션...", self)
        open_options.setShortcut("Ctrl+,")
        open_options.setStatusTip(
            "오리지날 경로 방식, 임포트 동작, 새 묶음 기본값을 정합니다.")
        open_options.triggered.connect(self._open_options)
        options_menu.addAction(open_options)
        options_menu.addSeparator()
        for text, slot, tip in (
            ("Wwise 우클릭 메뉴 등록", self._install_wwise_addon,
             "Wwise 프로젝트 익스플로러 우클릭에 Easy Sync 를 추가합니다."),
            ("탐색기 우클릭 메뉴 등록", self._install_shell_menu,
             "오디오 파일 우클릭에 'Easy Sync 로 보내기' 를 추가합니다."),
        ):
            action = QAction(text, self)
            action.setStatusTip(tip)
            action.triggered.connect(slot)
            options_menu.addAction(action)

        help_menu = bar.addMenu("도움말(&H)")
        update_action = QAction("업데이트 확인...", self)
        update_action.triggered.connect(self._check_updates)
        help_menu.addAction(update_action)

    def _check_updates(self) -> None:
        if self._importing:
            QMessageBox.information(self, "업데이트", "임포트가 완료된 후 업데이트해 주세요.")
            return
        from .update_dialog import UpdateDialog
        dialog = UpdateDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.close()

    def _open_options(self) -> None:
        previous_grouping = (self.settings.auto_group, self.settings.default_container)
        dialog = OptionsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 옵션 창에서 자동 묶기를 바꿨을 수 있다. 체크박스를 맞춘 뒤
            # 다시 묶는다 — 신호가 도로 돌지 않게 잠깐 막는다.
            for widget, value in (
                (self.auto_group_check, self.settings.auto_group),
                (self.smart_wav_check,
                 self.settings.originals_mode != options_dialog.MODE_MANUAL),
            ):
                widget.blockSignals(True)
                widget.setChecked(value)
                widget.blockSignals(False)
            self._regroup(reset_containers=previous_grouping != (
                self.settings.auto_group, self.settings.default_container))
            # 보이스 여부가 바뀌면 Sound 아이콘도 바뀐다.
            self._fill_group_tree()
            self._rebuild_plan()
            self.status.setText("옵션을 저장했습니다.")

    def _install_wwise_addon(self) -> None:
        from . import addon
        try:
            path = addon.install()
            reloaded = addon.reload_addons()
            QMessageBox.information(
                self, "Easy Sync",
                f"Wwise 우클릭 메뉴에 등록했습니다.\n{path}\n\n"
                + ("Wwise 가 애드온을 다시 읽었습니다. 바로 쓸 수 있습니다."
                   if reloaded else "Wwise 를 다시 시작하면 메뉴에 나타납니다."))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Easy Sync", f"등록 실패:\n{exc}")

    def _install_shell_menu(self) -> None:
        from . import shellmenu
        done = shellmenu.install()
        if done:
            QMessageBox.information(
                self, "Easy Sync",
                "탐색기 우클릭 메뉴에 등록했습니다.\n"
                + ", ".join(done)
                + f"\n\n오디오 파일을 우클릭하면 '{shellmenu.MENU_LABEL}' 이 보입니다.")
        else:
            QMessageBox.critical(self, "Easy Sync", "등록에 실패했습니다.")

    def _build_header(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(box)
        self.project_label = QLabel("Wwise 를 찾는 중...")
        font = self.project_label.font()
        font.setBold(True)
        self.project_label.setFont(font)
        row.addWidget(self.project_label)
        row.addStretch(1)
        self.root_warning = QLabel("")
        self.root_warning.setStyleSheet("color: #c08000;")
        self.root_warning.setVisible(False)
        row.addWidget(self.root_warning)
        # 중복 경고는 루트 경고와 다른 문제다. 같은 칸을 쓰면 하나가 다른
        # 하나를 덮어써서, 트리가 안 읽히는 진짜 원인이 보이지 않게 된다.
        self.instance_warning = QLabel("")
        self.instance_warning.setStyleSheet("color: #c08000;")
        self.instance_warning.setVisible(False)
        self.instance_warning.setToolTip(
            "Wwise 창을 하나만 띄우거나, 연결된 프로젝트가 맞는지\n"
            "머리말의 프로젝트 이름으로 확인하세요.")
        row.addWidget(self.instance_warning)
        refresh = QPushButton("Wwise 다시 읽기")
        refresh.setToolTip("계층과 스위치 그룹을 Wwise 에서 다시 읽습니다.")
        refresh.clicked.connect(self._reload_all)
        row.addWidget(refresh)
        return box

    # -- Wwise 연결 --------------------------------------------------------
    def _set_connection_status(self, text: str) -> None:
        """아직 못 붙었을 때 머리말과 상태줄에 같은 말을 띄운다."""
        if self.link.is_connected:
            return
        self.project_label.setText(text)
        self.project_label.setStyleSheet("color: #c08000;")
        self.status.setText(text)

    def _on_wwise_connected(self, project: ProjectInfo) -> None:
        """Wwise 에 붙었다(또는 프로젝트가 바뀌었다). 화면을 거기에 맞춘다."""
        self._save_project_pins()
        project_key = self.settings.project_key(project.path)
        self._pin_project_key = project_key
        audio_pins, event_pins = self.settings.pins_for_project(project.path)
        self.audio_panel.set_pins(audio_pins)
        self.event_panel.set_pins(event_pins)
        changed_project = (self._last_project_path is not None
                           and self._last_project_path != project_key)
        self._last_project_path = project_key
        if changed_project:
            self.settings.last_destination = ""
            self.settings.last_event_root = ""
            self._adopted_selection = False
            self.auto_event_check.setChecked(False)
            for group in self.groups:
                group.make_event = False
                group.switch_levels.clear()
                for source in group.files:
                    source.switches.clear()
            self._fill_group_tree()
        self._switch_lookup = {}
        self._destination_revision += 1
        self._destination_timer.stop()
        self._destination_loading = False
        self.project = project
        self.roots = project.roots
        bridge = self.link.bridge
        # install_dir() 은 WAAPI 왕복이다. 이 메서드는 UI 스레드에서 도는
        # 슬롯이라 여기서 직접 부르면 Wwise 가 바쁠 때 창이 통째로 멎는다.
        if bridge is not None:
            self.tasks.run(bridge.install_dir,
                           on_done=lambda folder: icons.configure(folder)
                           if self.project is project else None,
                           on_fail=lambda exc: log.debug("아이콘 경로 실패: %s", exc))

        self.setWindowTitle(f"Easy Sync  [{project.name}]")
        self.project_label.setText(
            f"프로젝트: {project.name}   |   {project.version}")
        self.project_label.setStyleSheet("")
        self.root_warning.setVisible(bool(self.roots.partial))
        if self.roots.partial:
            self.root_warning.setText("일부 계층 루트를 찾지 못했습니다: "
                                      + ", ".join(self.roots.missing))

        # 프로젝트가 바뀌면 예전 경로는 전부 무의미하다. 비우고 다시 고르게 한다.
        self.destination = ""
        self._existing_cache = frozenset()
        self._dest_segments = []
        self.event_root = self.settings.last_event_root or self.roots.events_default_wu

        self.audio_panel.set_source(bridge, self.roots.containers)
        self.event_panel.set_source(bridge, self.roots.events)
        self.audio_panel.reload(self.settings.last_destination)
        self.event_panel.reload(self.event_root)
        self._load_switch_groups()

        self.status.setText(f"Wwise 연결됨 — {project.name}")
        self._update_paths()
        self._rebuild_plan()
        # Wwise 선택을 가져오는 것은 **처음 붙을 때만** 한다. 재연결마다
        # 하면 사용자가 툴에서 골라 둔 목적지를 Wwise 에 남아 있던 엉뚱한
        # 선택이 덮어쓴다.
        if not self._adopted_selection:
            self._adopted_selection = True
            self._adopt_wwise_selection()
        self._warn_if_duplicate(project.name)
        self._queue_suggestion()

    def _warn_if_duplicate(self, project_name: str) -> None:
        """Wwise 가 여러 개 떠 있으면 알린다.

        WAAPI 포트는 먼저 뜬 쪽이 가져간다. 사용자가 보고 있는 창과 우리가
        말하는 창이 다를 수 있는데, 조용히 엉뚱한 프로젝트에 임포트하는 것이
        최악이다.
        """
        self.tasks.run(instances.duplicate_warning, project_name,
                       on_done=self._show_duplicate_warning,
                       on_fail=lambda exc: log.debug("인스턴스 확인 실패: %s", exc))

    def _show_duplicate_warning(self, message: str) -> None:
        self.instance_warning.setText(message)
        self.instance_warning.setVisible(bool(message))

    def _adopt_wwise_selection(self) -> None:
        """Wwise 에서 골라 둔 개체를 임포트 위치로 가져온다.

        Wwise 안에서 단축키나 우클릭으로 띄웠다면 이미 "여기" 를 고른
        상태다. 그걸 무시하고 저장된 위치를 쓰면 한 번 더 찾아 들어가야
        한다.

        오디오 계층에서 골랐으면 오디오 위치로, 이벤트 계층에서 골랐으면
        이벤트 위치로 간다 — 어느 탭에서 골랐는지가 곧 의도다.
        """
        bridge = self.link.bridge
        if bridge is None:
            return
        revision = self._destination_revision
        self.tasks.run(bridge.selected_paths,
                       on_done=lambda picked: self._on_selection_fetched(picked)
                       if revision == self._destination_revision else None,
                       on_fail=lambda exc: log.debug("선택 조회 실패: %s", exc))

    def _on_selection_fetched(self, picked: list[tuple[str, str]]) -> None:
        if not picked:
            return
        audio_root = self.roots.containers + schema.SEP
        event_root = self.roots.events + schema.SEP
        # 종류마다 **첫 번째 것만** 쓴다. 여러 개를 고른 채 단축키를 누르면
        # 전부 적용하다가 마지막 것이 이기는데, 그건 사용자가 보고 있던
        # 개체가 아니고 트리도 고른 수만큼 다시 읽힌다.
        took_audio = took_event = False
        for path, kind in picked:
            if (not took_audio and path.startswith(audio_root)
                    and kind in schema.DESTINATION_TYPES):
                took_audio = True
                self.audio_panel.reload(path)
                self._destination_chosen(path)
            elif not took_event and path.startswith(event_root):
                took_event = True
                self.event_panel.reload(path)
                self._event_root_chosen(path)
            if took_audio and took_event:
                break
        if took_audio or took_event:
            self.status.setText("Wwise 에서 고른 위치를 가져왔습니다.")

    def _on_wwise_lost(self, reason: str) -> None:
        """Wwise 가 사라졌다. 가져온 파일과 묶음은 그대로 두고 임포트만 막는다."""
        self._save_project_pins()
        self._pin_project_key = None
        self.audio_panel.set_pins([])
        self.event_panel.set_pins([])
        self.project = None
        self._destination_revision += 1
        self._destination_timer.stop()
        self._destination_loading = False
        self.audio_panel.set_source(None, "")
        self.event_panel.set_source(None, "")
        self._switch_lookup = {}
        self._existing_cache = frozenset()
        self._dest_segments = []
        self.destination = ""
        # 계획도 버린다. 남겨 두면 '만들어질 위치' 의 오리지날 줄이 이제는
        # 열려 있지도 않은 프로젝트의 경로를 계속 보여 준다.
        self.plan = None
        self._clear_statuses()
        self.import_button.setEnabled(False)
        self.summary_label.setText("")
        self.setWindowTitle("Easy Sync")
        self._set_connection_status(f"{reason} 다시 켜면 자동으로 붙습니다.")
        self._update_paths()

    def _require_wwise(self) -> WwiseBridge | None:
        """Wwise 가 필요한 동작 앞에서 부른다. 없으면 알려 주고 None."""
        bridge = self.link.bridge
        if bridge is None:
            QMessageBox.information(
                self, "Easy Sync",
                "Wwise 에 아직 연결되지 않았습니다.\n\n"
                "Wwise 를 켜면 몇 초 안에 자동으로 붙습니다.")
        return bridge

    def _build_audio_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>1. 오디오를 넣을 위치</b>"))
        # 트리는 Wwise 에 붙은 뒤에야 내용이 찬다(set_source).
        self.audio_panel = HierarchyPanel(
            self.tasks, schema.DESTINATION_TYPES,
            "오디오를 넣을 부모를 고르세요. 회색 항목은 자식을 받을 수 없습니다.")
        self.audio_panel.chosen.connect(self._destination_chosen)
        self.audio_panel.failed.connect(self._on_task_failed)
        layout.addWidget(self.audio_panel, 1)
        return panel

    def _build_event_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>2. 이벤트를 만들 위치</b>"))
        # 이벤트도 계층에서 고른다. 예전에는 경로를 직접 타이핑해야 했는데,
        # 오타가 나면 엉뚱한 곳에 폴더가 생겨 버린다.
        self.event_panel = HierarchyPanel(
            self.tasks, frozenset({"WorkUnit", "Folder", "PhysicalFolder"}),
            "이벤트를 만들 폴더를 고르세요. 없는 폴더는 임포트할 때 만들어집니다.")
        self.event_panel.chosen.connect(self._event_root_chosen)
        self.event_panel.failed.connect(self._on_task_failed)
        layout.addWidget(self.event_panel, 1)
        return panel

    def _build_work_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # 만들어질 위치를 묶음 트리 **위**에 둔다. 어디로 가는지 먼저 보고
        # 그 다음에 무엇을 보낼지 고르는 순서가 자연스럽다.
        layout.addWidget(self._build_paths_box())

        layout.addWidget(QLabel(
            "<b>3. 오디오 파일과 묶음</b>  (끌어다 놓아도 됩니다)"))

        row = QHBoxLayout()
        add = QPushButton("파일 추가...")
        add.setToolTip("임포트할 오디오 파일을 고릅니다. 창에 끌어다 놓아도 됩니다.")
        add.clicked.connect(self._pick_files)
        row.addWidget(add)
        clear = QPushButton("비우기")
        clear.setToolTip("목록의 파일을 모두 지웁니다. Wwise 는 건드리지 않습니다.")
        clear.clicked.connect(self._clear_files)
        row.addWidget(clear)
        self.auto_group_check = QCheckBox("자동 묶기")
        self.auto_group_check.setToolTip(
            "파일 이름의 끝 번호를 보고 비슷한 것끼리 자동으로 묶습니다.\n"
            "예: Creature_SFX_01/02/03 -> Creature_SFX 컨테이너 하나\n\n"
            "꺼 두면 가져온 그대로 낱개로 들어옵니다. 필요한 것만 골라\n"
            "우클릭으로 묶으면 됩니다.")
        self.auto_group_check.stateChanged.connect(self._auto_group_toggled)
        row.addWidget(self.auto_group_check)

        self.auto_event_check = QCheckBox("자동 이벤트")
        self.auto_event_check.setToolTip(
            "묶음과 낱개마다 이벤트를 만듭니다.\n"
            "켜면 지금 목록 전부의 이벤트 칸이 켜지고, 뒤에 가져오는\n"
            "파일도 켜진 채로 들어옵니다.\n\n"
            "이 선택은 저장하지 않습니다. 프로그램을 열 때마다 직접 켜 주세요.\n"
            "이벤트를 만들 위치는 왼쪽 '이벤트를 만들 위치' 에서 고릅니다.")
        self.auto_event_check.stateChanged.connect(self._auto_event_toggled)
        row.addWidget(self.auto_event_check)

        self.smart_wav_check = QCheckBox("스마트 wav")
        self.smart_wav_check.setToolTip(
            "원본 wav 를 둘 곳을 정하는 방식입니다.\n\n"
            "켜짐 — 옵션에 정해 둔 대로 Wwise 계층을 따라 폴더를 만듭니다.\n"
            "꺼짐 — 임포트할 때 폴더 선택 창이 떠서 직접 고릅니다.\n\n"
            "무엇이 켜져 있든 '만들어질 위치' 의 오리지날 wav 줄에\n"
            "실제 경로가 나옵니다.")
        self.smart_wav_check.stateChanged.connect(self._smart_wav_toggled)
        row.addWidget(self.smart_wav_check)

        self.suggest_check = QCheckBox("경로 추천")
        self.suggest_check.setToolTip(
            "파일 이름을 _ 로 쪼갠 단어로 Wwise 를 뒤져 넣을 만한 위치를\n"
            "찾아 줍니다. 맞다 싶으면 [적용] 을 누르세요.\n\n"
            "추천일 뿐이라 누르기 전에는 아무것도 바뀌지 않습니다.")
        self.suggest_check.stateChanged.connect(self._suggest_toggled)
        row.addWidget(self.suggest_check)

        row.addStretch(1)
        layout.addLayout(row)

        self.group_tree = QTreeWidget()
        self.group_tree.setHeaderLabels(["이름", "컨테이너", "이벤트", "스위치", "상태"])
        # Keep model/name column 0; move the event column visually to the left.
        self.group_tree.header().moveSection(2, 0)
        self.group_tree.setTreePosition(0)
        self.group_tree.setColumnWidth(0, 320)
        self.group_tree.setColumnWidth(1, 170)
        self.group_tree.setColumnWidth(2, 64)
        self.group_tree.setColumnWidth(3, 130)
        self.group_tree.itemChanged.connect(self._group_item_changed)
        self.group_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.group_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_tree.customContextMenuRequested.connect(self._group_menu)
        self.group_tree.setToolTip(
            "묶음을 두 개 이상 골라 우클릭하면 합칠 수 있고,\n"
            "파일을 골라 우클릭하면 따로 떼어낼 수 있습니다.\n"
            "이름은 더블클릭해서 고칩니다.")
        layout.addWidget(self.group_tree, 3)

        layout.addWidget(QLabel("확인이 필요한 항목"))
        self.issue_list = QTreeWidget()
        self.issue_list.setHeaderLabels(["", "내용"])
        self.issue_list.setColumnWidth(0, 56)
        self.issue_list.setRootIsDecorated(False)
        self.issue_list.setMaximumHeight(96)
        layout.addWidget(self.issue_list)
        return panel

    def _build_paths_box(self) -> QWidget:
        """무엇이 어디에 만들어지는지 한자리에서 보여 준다.

        예전에는 임포트 위치가 왼쪽 아래에, Originals 경로가 가운데에 따로
        있어서 세 경로를 한눈에 맞춰 보기 어려웠다.
        """
        box = QGroupBox("만들어질 위치")
        grid = QVBoxLayout(box)
        grid.setSpacing(3)
        self.path_labels: dict[str, PathDisplay] = {}
        for key, caption in (("container", "컨테이너"),
                             ("originals", "오리지날 wav"),
                             ("event", "이벤트")):
            row = QHBoxLayout()
            cap = QLabel(caption)
            # 12pt 에서 "오리지날 wav" 가 들어가는 너비. 좁으면 값과 붙는다.
            cap.setMinimumWidth(130)
            cap.setStyleSheet("color: #9a9a9a;")
            row.addWidget(cap, 0, Qt.AlignmentFlag.AlignTop)
            value = PathDisplay("—")
            value.setStyleSheet("font-family: Consolas, monospace; background: transparent;")
            self.path_labels[key] = value
            row.addWidget(value, 1)
            grid.addLayout(row)

        # 추천 줄. 쓸 것이 없으면 통째로 숨긴다 — 빈 줄이 자리만 차지하면
        # 세 경로를 읽는 흐름이 끊긴다.
        self.suggest_row = QWidget()
        suggest_layout = QHBoxLayout(self.suggest_row)
        suggest_layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel("추천 위치")
        caption.setMinimumWidth(130)
        caption.setStyleSheet("color: #6a9;")
        suggest_layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)
        self.suggest_label = PathDisplay("")
        self.suggest_label.setStyleSheet("color: #6a9; font-family: Consolas; background: transparent;")
        suggest_layout.addWidget(self.suggest_label, 1)
        self.suggest_apply = QPushButton("적용")
        self.suggest_apply.setToolTip("추천한 위치를 임포트 위치로 삼습니다.")
        self.suggest_apply.clicked.connect(self._apply_suggestion)
        suggest_layout.addWidget(self.suggest_apply)
        self.suggest_row.setVisible(False)
        grid.addWidget(self.suggest_row)
        return box

    def _build_footer(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(box)
        self.status = QLabel("준비됨")
        row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        row.addWidget(self.progress)
        self.summary_label = QLabel("")
        row.addWidget(self.summary_label)
        self.import_button = QPushButton("임포트")
        self.import_button.setMinimumWidth(150)
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self._do_import)
        self.import_button.setEnabled(False)
        row.addWidget(self.import_button)
        return box

    # -- 설정 --------------------------------------------------------------
    def _restore_settings(self) -> None:
        """설정을 화면에 반영한다.

        옵션 값 자체는 위젯이 아니라 ``self.settings`` 에 산다 — 옵션 창에서
        고치기 때문이다. 여기서는 메인 창에 남아 있는 것만 채운다.
        """
        s = self.settings
        self.auto_group_check.setChecked(s.auto_group)
        self.auto_event_check.setChecked(False)
        self.suggest_check.setChecked(s.suggest_paths)
        self.smart_wav_check.setChecked(
            s.originals_mode != options_dialog.MODE_MANUAL)
        # 핀은 연결된 프로젝트를 확인한 뒤 그 프로젝트의 목록만 불러온다.
        # 트리 내용은 여기서 읽지 않는다. Wwise 에 붙은 뒤
        # _on_wwise_connected 가 지난번 위치까지 펼쳐 준다.
        self._update_paths()

    def _on_pin_unavailable(self, panel: HierarchyPanel, path: str) -> None:
        if panel is self.audio_panel:
            self._destination_revision += 1
            self._destination_timer.stop()
            self._destination_loading = False
            self.destination = self.settings.last_destination = ""
            self._existing_cache = frozenset()
            self._dest_segments = []
        else:
            self.event_root = self.settings.last_event_root = ""
        self._update_paths()
        self._rebuild_plan()
        self.status.setText(f"핀 경로를 찾을 수 없어 전체 보기로 전환했습니다: {path}")

    def _save_project_pins(self) -> None:
        if self._pin_project_key is not None and self.settings.store_project_pins(
                self._pin_project_key, self.audio_panel.pins, self.event_panel.pins):
            self.settings.save()

    def _persist(self) -> None:
        s = self.settings
        s.auto_group = self.auto_group_check.isChecked()
        s.suggest_paths = self.suggest_check.isChecked()
        s.last_event_root = self.event_root
        s.last_destination = self.destination
        self._save_project_pins()
        s.save()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 이름
        if self._importing:
            event.ignore()
            self.status.setText("임포트가 완료된 후 종료할 수 있습니다.")
            return
        self._persist()
        super().closeEvent(event)

    def _reload_all(self) -> None:
        if self._importing:
            self.status.setText("임포트가 완료된 후 다시 읽을 수 있습니다.")
            return
        self.link.check_now()
        if self.link.bridge is None:
            return
        self.audio_panel.reload(self.destination)
        self.event_panel.reload(self.event_root)
        self._load_switch_groups()

    # -- 위치 선택 ---------------------------------------------------------
    def _destination_chosen(self, path: str) -> None:
        if self.link.bridge is None:
            return
        if path == self.destination and not self._destination_loading:
            return
        self._destination_revision += 1
        self.destination = path
        self.settings.last_destination = path
        self._existing_cache = frozenset()
        self._dest_segments = []
        self._destination_loading = True
        self._rebuild_plan()
        self._update_paths()
        self._destination_timer.start()

    def _fetch_destination(self) -> None:
        bridge, path = self.link.bridge, self.destination
        revision = self._destination_revision
        if bridge is None or not path:
            return
        def fetch():
            return bridge.existing_paths(path), bridge.path_segments(path)
        def current():
            return (revision == self._destination_revision
                    and bridge is self.link.bridge and path == self.destination)
        def done(result):
            if current():
                self._existing_cache, self._dest_segments = result
                self._destination_loading = False
                self._rebuild_plan()
        def failed(exc):
            if current():
                self._on_task_failed(exc)
        self.tasks.run(fetch, on_done=done, on_fail=failed)

    def _event_root_chosen(self, path: str) -> None:
        self.event_root = path
        self._update_paths()
        self._queue_replan()

    def _on_existing_loaded(self, paths: frozenset[str]) -> None:
        self._existing_cache = paths
        self._rebuild_plan()

    def _on_segments_loaded(self, segments: list[tuple[str, str]]) -> None:
        self._dest_segments = segments
        self._rebuild_plan()

    def _update_paths(self) -> None:
        """'만들어질 위치' 세 줄을 갱신한다.

        Wwise 에 붙기 전에도 불린다. ``self.project`` 가 없을 수 있으므로
        언어 폴더를 project 에서 읽을 때 반드시 확인한다 — 예전에는 보이스
        임포트가 켜져 있으면 여기서 창 생성 자체가 터졌다.
        """
        self.path_labels["container"].setText(
            self.destination or "— 왼쪽 '오디오를 넣을 위치' 에서 고르세요")
        self.path_labels["event"].setText(
            self.event_root or "— 왼쪽 '이벤트를 만들 위치' 에서 고르세요")

        language = self.project.default_language if self.project else ""
        language_dir = (f"Voices\\{language or '<언어>'}"
                        if self.settings.is_voice else "SFX")
        sounds = list(_iter_sounds(self.plan.nodes)) if self.plan else []
        if sounds:
            sub = sounds[0].originals
            distinct = {n.originals for n in sounds}
            tail = f"   (경로 {len(distinct)}종류)" if len(distinct) > 1 else ""
            shown = (f"Originals\\{language_dir}\\"
                     + (f"{sub}\\" if sub else "") + f"{sounds[0].name}.wav{tail}")
        else:
            shown = f"Originals\\{language_dir}\\ ..."
        self.path_labels["originals"].setText(shown)

    # -- 파일 --------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths: list[Path] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths.extend(p for p in sorted(path.rglob("*"))
                             if p.suffix.lower() in AUDIO_SUFFIXES)
            elif path.suffix.lower() in AUDIO_SUFFIXES:
                paths.append(path)
        if paths:
            self.add_files(paths)
            event.acceptProposedAction()

    def _on_files_received(self, paths: list[Path]) -> None:
        self._incoming_paths.extend(paths)
        self._incoming_timer.start()

    def _flush_incoming_files(self) -> None:
        from .app import _collect_files
        paths, self._incoming_paths = list(dict.fromkeys(self._incoming_paths)), []
        log.info("탐색기에서 경로 %d개 수신", len(paths))
        self.tasks.run(_collect_files, [str(p) for p in paths], on_done=self.add_files,
                       on_fail=self._on_task_failed)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "오디오 파일 선택", "",
            "오디오 파일 (*.wav *.aif *.aiff *.flac *.ogg);;모든 파일 (*.*)")
        if files:
            self.add_files([Path(f) for f in files])

    def add_files(self, paths: list[Path]) -> None:
        known = {f.path for g in self.groups for f in g.files}
        paths = [p.absolute() for p in paths]
        fresh = list(dict.fromkeys(p for p in paths if p not in known))
        if not fresh:
            return
        self._rebuild_groups([f.path for g in self.groups for f in g.files] + fresh)
        log.info("오디오 목록: 총 %d개 (이번 추가 %d개)",
                 sum(len(g.files) for g in self.groups), len(fresh))

    def _clear_files(self) -> None:
        self.groups = []
        self.group_tree.clear()
        self._rebuild_plan()

    def _auto_event_toggled(self, state: int) -> None:
        """자동 이벤트를 켜고 끈다. 지금 목록에도 바로 반영한다.

        새로 가져오는 파일에만 적용하면 "켰는데 아무 일도 안 일어난다" 가
        된다. 이미 있는 줄까지 맞춰 주는 쪽이 기대에 맞다.
        """
        on = state == Qt.CheckState.Checked.value
        for group in self.groups:
            group.make_event = on
        self._fill_group_tree()
        self._rebuild_plan()

    def _suggest_toggled(self, state: int) -> None:
        self.settings.suggest_paths = state == Qt.CheckState.Checked.value
        self._queue_suggestion()

    def _refresh_suggestion(self) -> None:
        """파일 이름으로 넣을 만한 위치를 찾는다.

        백그라운드로 돌린다 — 단어마다 WAAPI 검색이 한 번씩 나가므로
        UI 스레드에서 하면 창이 멎는다.
        """
        self._suggestion = None
        self.suggest_row.setVisible(False)
        bridge = self.link.bridge
        if bridge is None or not self.settings.suggest_paths or not self.groups:
            return
        names = [f.path.name for g in self.groups for f in g.files][:40]
        root = self.roots.containers
        self.tasks.run(suggest.suggest_paths, bridge, names, root,
                       on_done=self._on_suggestion,
                       on_fail=lambda exc: log.debug("추천 실패: %s", exc))

    def _on_suggestion(self, found: list) -> None:
        if not found:
            self.suggest_row.setVisible(False)
            return
        best = found[0]
        self._suggestion = best.path
        self.suggest_label.setText(f"{best.path}    ({best.reason()})")
        self.suggest_row.setVisible(True)

    def _apply_suggestion(self) -> None:
        if not self._suggestion:
            return
        path = self._suggestion
        self.audio_panel.reload(path)
        self._destination_chosen(path)
        self.suggest_row.setVisible(False)
        self.status.setText(f"추천 위치를 적용했습니다 — {path}")

    def _smart_wav_toggled(self, state: int) -> None:
        """원본 wav 경로를 자동(스마트)으로 할지 직접 고를지 바꾼다."""
        self.settings.originals_mode = (
            options_dialog.MODE_SMART if state == Qt.CheckState.Checked.value
            else options_dialog.MODE_MANUAL)
        self._rebuild_plan()

    def _auto_group_toggled(self, state: int) -> None:
        """자동 묶기를 켜고 끈다. 지금 있는 파일에 즉시 반영한다."""
        self.settings.auto_group = state == Qt.CheckState.Checked.value
        self._regroup()

    def _regroup(self, *, reset_containers: bool = True) -> None:
        self._rebuild_groups([f.path for g in self.groups for f in g.files],
                             preserve_containers=not reset_containers)

    def _rebuild_groups(self, paths: list[Path], *, preserve_containers: bool = True) -> None:
        """파일 목록에서 그룹을 다시 만든다.

        파일 추가는 같은 파일을 포함한 기존 묶음의 수동 선택을 유지한다.
        명시적 자동 재묶기는 컨테이너 기본값을 적용하며 이전 타입을 복원하지 않는다.
        """
        previous = {g.key: g for g in self.groups}
        self.groups = plan_mod.group_files(
            paths, container=self.settings.default_container,
            auto=self.settings.auto_group)
        if self.auto_event_check.isChecked():
            for group in self.groups:
                group.make_event = True
        for group in self.groups:
            old = previous.get(group.key)
            if old and {f.path for f in old.files}.intersection(f.path for f in group.files):
                group.make_event = old.make_event
                group.event_name = old.event_name
                if preserve_containers:
                    group.container = old.container
                    group.switch_levels = list(old.switch_levels)
                old_files = {f.path: f for f in old.files}
                for f in group.files:
                    previous_file = old_files.get(f.path)
                    if previous_file:
                        f.include = previous_file.include
                        f.object_name = previous_file.object_name
                        if preserve_containers:
                            f.switches = list(previous_file.switches)
        self._fill_group_tree()
        self._rebuild_plan()
        self._queue_suggestion()

    def _queue_suggestion(self) -> None:
        self._suggestion = None
        self.suggest_row.setVisible(False)
        if self.settings.suggest_paths:
            self._suggest_timer.start()

    def _fill_group_tree(self) -> None:
        """묶음 트리를 다시 그린다.

        두 가지 모양이 있다.

          낱개 파일 — 컨테이너가 없는 한 개짜리. 최상위에 한 줄로만 나온다.
                     컨테이너 콤보도 체크박스도 없다. 그냥 Sound 하나다.
          묶음      — 컨테이너가 붙은 것. 굵은 제목 줄 아래 파일들이 달리고,
                     파일마다 포함 여부 체크박스가 붙는다.

        낱개를 "컨테이너 없음" 묶음으로 그리지 않는 이유: 파일 하나를 그냥
        넣고 싶을 뿐인데 접혔다 펴지는 묶음과 빈 콤보가 따라붙으면 읽기만
        번거롭다. 눈에 보이는 모양이 하는 일과 같아야 한다.
        """
        self.group_tree.blockSignals(True)
        self.group_tree.clear()
        sound_icon = icons.for_token(
            schema.SOUND_VOICE if self.settings.is_voice else schema.SOUND_SFX)

        for group in self.groups:
            if self._is_loose(group):
                self._add_loose_row(group, sound_icon)
            else:
                self._add_group_rows(group, sound_icon)
        self.group_tree.setColumnWidth(3, self._switch_column_width())
        self.group_tree.blockSignals(False)

    @staticmethod
    def _is_loose(group: plan_mod.Group) -> bool:
        """묶이지 않은 낱개 파일인가."""
        return group.container == schema.NO_CONTAINER and len(group.files) == 1

    def _add_loose_row(self, group: plan_mod.Group, sound_icon) -> None:
        source = group.files[0]
        item = QTreeWidgetItem(self.group_tree, [source.name, "", "", "", ""])
        item.setData(0, ROLE_KIND, KIND_FILE)
        item.setData(0, ROLE_NODE, source)
        # 낱개 줄은 그룹이기도 하다. 이벤트 체크나 컨테이너 지정은 그룹
        # 단위로 돌아가므로 뒤에 있는 그룹을 함께 달아 둔다.
        item.setData(0, ROLE_GROUP, group)
        item.setIcon(0, sound_icon)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(0, str(source.path))

        check = QCheckBox()
        check.setChecked(group.make_event)
        check.setToolTip("체크하면 이 사운드를 재생하는 이벤트를 만듭니다.")
        check.stateChanged.connect(
            lambda state, g=group: self._event_toggled(g, state))
        self.group_tree.setItemWidget(item, 2, check)

    def _add_group_rows(self, group: plan_mod.Group, sound_icon) -> None:
        item = QTreeWidgetItem(self.group_tree, [group.key, "", "", "", ""])
        item.setData(0, ROLE_KIND, KIND_GROUP)
        item.setData(0, ROLE_NODE, group)
        item.setData(0, ROLE_GROUP, group)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setIcon(0, icons.for_token(group.container))
        font = QFont()
        font.setBold(True)
        item.setFont(0, font)

        combo = ContainerComboBox()
        combo.addItem("묶지 않음", schema.NO_CONTAINER)
        for token, label in schema.GROUP_CONTAINERS:
            combo.addItem(icons.for_token(token), label, token)
        index = combo.findData(group.container)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, g=group, c=combo: self._container_changed(g, c))
        combo.setToolTip(
            "이 묶음을 담을 컨테이너 종류입니다.\n"
            "묶음을 여러 개 골라 두면 고른 전부에 함께 적용됩니다.")
        self.group_tree.setItemWidget(item, 1, combo)

        check = QCheckBox()
        check.setChecked(group.make_event)
        check.setToolTip("체크하면 이 컨테이너를 재생하는 이벤트를 만듭니다.")
        check.stateChanged.connect(
            lambda state, g=group: self._event_toggled(g, state))
        self.group_tree.setItemWidget(item, 2, check)

        if group.container == "Switch Container":
            self.group_tree.setItemWidget(item, 3,
                                          self._switch_levels_widget(group))

        for source in group.files:
            child = QTreeWidgetItem(item, [source.name, "", "", "", ""])
            child.setData(0, ROLE_KIND, KIND_FILE)
            child.setData(0, ROLE_NODE, source)
            child.setData(0, ROLE_GROUP, group)
            child.setIcon(0, sound_icon)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable
                           | Qt.ItemFlag.ItemIsEditable)
            child.setCheckState(
                0, Qt.CheckState.Checked if source.include
                else Qt.CheckState.Unchecked)
            child.setToolTip(
                0, f"{source.path}\n체크를 끄면 이 파일만 빠집니다.")
            if group.container == "Switch Container":
                self.group_tree.setItemWidget(
                    child, 3, self._switch_values_widget(group, source))
        item.setExpanded(True)

    def _levels_of(self, group: plan_mod.Group) -> list[str]:
        '''화면에 그릴 단계 목록. 비어 있어도 한 칸은 보여 준다.'''
        return list(group.switch_levels[:1]) or [""]

    def _switch_levels_widget(self, group: plan_mod.Group) -> QWidget:
        '''스위치 그룹 하나만 지정한다.'''
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        levels = self._levels_of(group)
        for level, current in enumerate(levels):
            combo = QComboBox()
            combo.addItem("(스위치 그룹)", "")
            for path in sorted(self._switch_lookup):
                info = self._switch_lookup[path]
                combo.addItem(icons.for_type(info.get("type", "")),
                              path.rsplit(schema.SEP, 1)[-1], path)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setToolTip(
                "스위치/스테이트 그룹을 선택합니다.")
            combo.currentIndexChanged.connect(
                lambda _i, g=group, lv=level, c=combo:
                self._switch_group_changed(g, lv, c))
            row.addWidget(combo)

        return holder

    def _switch_values_widget(self, group: plan_mod.Group,
                              source: plan_mod.SourceFile) -> QWidget:
        '''파일 줄의 단계별 스위치 값.'''
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        for level, path in enumerate(self._levels_of(group)):
            combo = QComboBox()
            combo.addItem("(미지정)", "")
            info = self._switch_lookup.get(path)
            for name in (info or {}).get("children", {}):
                combo.addItem(name, name)
            combo.setEnabled(bool(info))
            index = combo.findData(source.switch_at(level))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setToolTip(f"{level + 1}단계에서 이 파일이 배정될 값입니다.")
            combo.currentIndexChanged.connect(
                lambda _i, sf=source, lv=level, c=combo:
                self._switch_value_changed(sf, lv, c))
            row.addWidget(combo)
        return holder

    def _switch_value_changed(self, source: plan_mod.SourceFile, level: int,
                              combo: QComboBox) -> None:
        source.set_switch_at(level, combo.currentData() or "")
        self._queue_replan()

    def _switch_column_width(self) -> int:
        return 160

    def _container_changed(self, group: plan_mod.Group, combo: QComboBox) -> None:
        """컨테이너 종류를 바꾼다. 여러 묶음을 골라 뒀으면 전부에 적용한다.

        한 번에 수십 개를 가져오는 일이 흔한데 콤보가 자기 줄에만 듣는다면
        같은 선택을 수십 번 되풀이해야 한다.
        """
        token = combo.currentData()
        targets = [g for g in self._selected_groups() if g is not group]
        group.container = token
        for other in targets:
            other.container = token
        if targets:
            self.status.setText(f"묶음 {len(targets) + 1}개에 적용했습니다.")
        # 스위치 컨테이너로 바뀌면 스위치 열이 필요하므로 트리를 다시 그린다.
        # 다만 지금 이 호출은 그 트리 안의 콤보가 낸 시그널 위에서 돌고 있다.
        # 여기서 바로 다시 그리면 신호를 낸 콤보가 자기 슬롯 안에서 삭제된다.
        # 이벤트 루프로 한 번 넘긴 뒤에 그린다.
        self._redraw_tree_soon()

    def _redraw_tree_soon(self) -> None:
        """묶음 트리를 다음 이벤트 루프 차례에 다시 그린다.

        트리 안의 위젯(콤보·체크박스)이 낸 시그널을 처리하는 도중에
        ``_fill_group_tree`` 를 부르면 ``clear()`` 가 그 위젯을 지운다 —
        자기 슬롯이 아직 스택에 있는 상태에서. Qt 에서 이건 정의되지 않은
        동작이고 보통 'Internal C++ object already deleted' 로 터진다.
        """
        QTimer.singleShot(0, self._redraw_tree_now)

    def _redraw_tree_now(self) -> None:
        self._fill_group_tree()
        self._rebuild_plan()

    def _selected_groups(self) -> list[plan_mod.Group]:
        """지금 고른 줄들이 속한 묶음. 중복은 없앤다."""
        found: list[plan_mod.Group] = []
        for item in self.group_tree.selectedItems():
            grp = item.data(0, ROLE_GROUP)
            if grp is not None and grp not in found:
                found.append(grp)
        return found

    def _event_toggled(self, group: plan_mod.Group, state: int) -> None:
        group.make_event = state == Qt.CheckState.Checked.value
        self._queue_replan()

    def _switch_group_changed(self, group: plan_mod.Group, level: int,
                              combo: QComboBox) -> None:
        """그룹 하나를 지정하고 이전 그룹의 값은 비운다."""
        value = combo.currentData() or ""
        group.switch_levels = [value] if value else []
        for source in group.files:
            source.switches = []
        assigned = self._auto_assign_switches(group)
        # 위와 같은 이유로 미룬다 — 이 콤보가 낸 시그널 위에서 돌고 있다.
        self._redraw_tree_soon()
        if assigned:
            self.status.setText(
                f"'{group.key}': 파일 {assigned}개를 이름으로 스위치에 맞췄습니다.")

    def _auto_assign_switches(self, group: plan_mod.Group) -> int:
        """파일 이름에서 스위치를 찾아 배정한다. 배정한 개수를 돌려준다.

        표면·상태별로 파일이 수십 개씩 오는데 하나씩 콤보를 고르는 것은
        일이 아니다. 이름에 이미 답이 들어 있으므로(``..._Sand_...``,
        ``PM01_Sand/``) 거기서 찾는다.

        이미 손으로 정해 둔 것은 건드리지 않는다 — 자동이 손보다 우선하면
        고쳐 놓은 것이 되돌아간다.
        """
        assigned = 0
        for level, path in enumerate(group.switch_levels):
            info = self._switch_lookup.get(path)
            if not info:
                continue
            names = list(info.get("children", {}))
            if not names:
                continue
            for source in group.files:
                if source.switch_at(level):
                    continue
                found = naming.match_switch(source.path, names)
                if found:
                    source.set_switch_at(level, found)
                    assigned += 1
        return assigned

    def _group_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        kind = item.data(0, ROLE_KIND)
        node = item.data(0, ROLE_NODE)
        if kind == KIND_FILE and node is not None:
            # 낱개 줄에는 포함 체크박스가 없다. 없는 체크박스를 읽으면
            # 항상 Unchecked 가 나와 파일이 통째로 빠진다.
            if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                node.include = item.checkState(0) == Qt.CheckState.Checked
            if column == 0:
                node.object_name = item.text(0)
        elif kind == KIND_GROUP and node is not None and column == 0:
            node.key = item.text(0)
        self._queue_replan()

    def _group_menu(self, pos) -> None:
        item = self.group_tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        source = item.data(0, ROLE_NODE)
        if isinstance(source, plan_mod.SourceFile):
            action = menu.addAction("가져온 원본 파일 찾기")
            action.setToolTip(str(source.path))
            action.triggered.connect(lambda: self._reveal_source(source.path))
            menu.addSeparator()
        for label, slot, tip in (
            ("선택한 것을 컨테이너로 묶기", self._group_selected,
             "고른 파일과 묶음을 컨테이너 하나로 모읍니다."),
            ("묶음 풀기 (낱개로)", self._ungroup_selected,
             "고른 묶음의 컨테이너를 없애고 파일을 낱개로 되돌립니다."),
            ("선택한 파일 따로 떼기", self._split_selected,
             "고른 파일들을 지금 묶음에서 빼내 새 묶음으로 만듭니다."),
            ("묶음 전부 낱개로 풀기", self._explode_selected,
             "고른 묶음의 파일을 하나씩 별도 묶음으로 흩뜨립니다."),
            ("스위치 이름으로 다시 맞추기", self._rematch_switches,
             "파일 이름에서 스위치를 찾아 다시 배정합니다."),
            ("스위치 그룹 다시 읽기", self._reload_switch_groups,
             "Wwise 에서 스위치/스테이트 그룹 목록을 새로 가져옵니다."),
            ("선택 항목 제거", self._remove_selected,
             "고른 항목을 목록에서 뺍니다. Wwise 는 건드리지 않습니다."),
        ):
            action = QAction(label, self)
            action.setToolTip(tip)
            action.setStatusTip(tip)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.addSeparator()
        for label, value in (("모두 이벤트 켜기", True), ("모두 이벤트 끄기", False)):
            action = QAction(label, self)
            action.triggered.connect(lambda _c=False, v=value: self._set_all_events(v))
            menu.addAction(action)
        menu.exec(self.group_tree.viewport().mapToGlobal(pos))

    def _reveal_source(self, path: Path) -> None:
        from .source_location import reveal
        try:
            reveal(path)
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, "원본 파일 찾기", str(exc))

    def _merge_selected(self) -> None:
        """고른 그룹들을 첫 번째 그룹으로 합친다.

        이름 규칙만으로는 묶이지 않는 파일들(예: 라이브러리에서 받은 긴 이름)
        을 손으로 한 컨테이너에 모을 수 있어야 한다.
        """
        chosen = [item.data(0, ROLE_NODE) for item in self.group_tree.selectedItems()
                  if item.data(0, ROLE_KIND) == KIND_GROUP]
        if len(chosen) < 2:
            self.status.setText("합치려면 그룹을 두 개 이상 고르세요.")
            return
        target = chosen[0]
        for other in chosen[1:]:
            target.files.extend(other.files)
            self.groups.remove(other)
        self._fill_group_tree()
        self._rebuild_plan()

    def _group_selected(self) -> None:
        """고른 파일·묶음을 컨테이너 하나로 모은다.

        기본은 묶지 않고 들여놓는 것이라, 묶는 행위는 항상 사용자가 고른
        뒤에 일어난다. 이름 규칙이 맞아떨어지지 않는 조합도 손으로 묶을 수
        있어야 한다.
        """
        groups = self._selected_groups()
        files: list[plan_mod.SourceFile] = []
        for group in groups:
            files.extend(group.files)
        if len(files) < 2:
            self.status.setText("묶으려면 파일을 두 개 이상 고르세요.")
            return

        key = self._unique_key(
            naming.group_key(files[0].path.name))
        merged = plan_mod.Group(
            key=key, files=files,
            container=self.settings.default_container or "Random Container",
            make_event=self.auto_event_check.isChecked())
        first = min(self.groups.index(g) for g in groups)
        self.groups = [g for g in self.groups if g not in groups]
        self.groups.insert(first, merged)
        self._fill_group_tree()
        self._rebuild_plan()
        self.status.setText(f"파일 {len(files)}개를 '{key}' 로 묶었습니다.")

    def _ungroup_selected(self) -> None:
        """고른 묶음의 컨테이너를 없애고 낱개 파일로 되돌린다."""
        groups = [g for g in self._selected_groups() if not self._is_loose(g)]
        if not groups:
            self.status.setText("풀 묶음을 고르세요.")
            return
        for group in groups:
            index = self.groups.index(group)
            loose = [plan_mod.Group(key=f.name, files=[f],
                                    container=schema.NO_CONTAINER)
                     for f in group.files]
            self.groups[index:index + 1] = loose
        self._fill_group_tree()
        self._rebuild_plan()

    def _split_selected(self) -> None:
        """고른 파일들을 지금 묶음에서 빼내 새 묶음으로 만든다.

        자동 묶기는 이름만 보고 하는 추측이라 늘 맞지는 않는다. 합치는 것만
        되고 떼는 것이 안 되면, 잘못 묶였을 때 파일을 다 지우고 다시
        가져오는 수밖에 없다.
        """
        chosen = [item.data(0, ROLE_NODE) for item in self.group_tree.selectedItems()
                  if item.data(0, ROLE_KIND) == KIND_FILE]
        if not chosen:
            self.status.setText("떼어낼 파일을 고르세요.")
            return

        moved: list[plan_mod.SourceFile] = []
        for group in self.groups:
            for source in list(group.files):
                if source in chosen:
                    group.files.remove(source)
                    moved.append(source)
        if not moved:
            return

        # 새 묶음 이름은 뗀 파일들의 공통 이름에서 뽑는다. 하나뿐이면 그 이름.
        key = naming.group_key(moved[0].path.name)
        key = self._unique_key(key)
        self.groups.append(plan_mod.Group(
            key=key, files=moved, container=self.settings.default_container,
            make_event=self.auto_event_check.isChecked()))
        self.groups = [g for g in self.groups if g.files]
        self._fill_group_tree()
        self._rebuild_plan()
        self.status.setText(f"파일 {len(moved)}개를 '{key}' 묶음으로 뗐습니다.")

    def _explode_selected(self) -> None:
        """고른 묶음을 파일 하나짜리 묶음들로 흩뜨린다."""
        chosen = [item.data(0, ROLE_NODE) for item in self.group_tree.selectedItems()
                  if item.data(0, ROLE_KIND) == KIND_GROUP]
        if not chosen:
            self.status.setText("풀어낼 묶음을 고르세요.")
            return
        for group in chosen:
            if len(group.files) < 2:
                continue
            rest = group.files[1:]
            group.files = group.files[:1]
            for source in rest:
                self.groups.append(plan_mod.Group(
                    key=self._unique_key(naming.object_name(
                        source.path.name)),
                    files=[source], container=group.container,
                    make_event=group.make_event))
        self._fill_group_tree()
        self._rebuild_plan()

    def _reload_switch_groups(self) -> None:
        """Wwise 에서 스위치/스테이트 그룹을 다시 읽는다.

        툴을 켜 둔 채 Wwise 에서 스위치를 새로 만드는 일이 흔하다. 그때
        툴을 다시 켜게 하지 않는다.
        """
        if self.link.bridge is None:
            self.status.setText("Wwise 에 연결되어 있지 않습니다.")
            return
        self.status.setText("스위치 그룹을 읽는 중...")
        self._load_switch_groups()

    def _rematch_switches(self) -> None:
        """고른 묶음의 스위치 배정을 이름으로 다시 계산한다.

        손으로 고친 것도 여기서는 지운다 — "다시 맞추기" 를 누른 사람은
        지금 배정을 버리고 싶은 것이다.
        """
        # 고른 것이 있으면 **그 안에서만** 다시 맞춘다. 예전에는 고른
        # 묶음에 스위치 그룹이 없으면 전체로 번져서, 손대지 않은 묶음의
        # 손수 배정까지 지웠다.
        selected = self._selected_groups()
        if selected:
            groups = [g for g in selected if g.switch_group]
            if not groups:
                self.status.setText("고른 묶음에 스위치 그룹이 지정되어 있지 않습니다.")
                return
        else:
            groups = [g for g in self.groups if g.switch_group]
        if not groups:
            self.status.setText("스위치 그룹이 지정된 묶음이 없습니다.")
            return
        total = 0
        for group in groups:
            for source in group.files:
                source.switches = []
            total += self._auto_assign_switches(group)
        self._fill_group_tree()
        self._rebuild_plan()
        self.status.setText(f"스위치 {total}개를 이름으로 다시 맞췄습니다.")

    def _unique_key(self, key: str) -> str:
        """묶음 이름이 겹치지 않게 뒤에 번호를 붙인다."""
        taken = {g.key for g in self.groups}
        if key not in taken:
            return key
        for n in range(2, 999):
            candidate = f"{key}_{n}"
            if candidate not in taken:
                return candidate
        return key

    def _remove_selected(self) -> None:
        for item in self.group_tree.selectedItems():
            kind = item.data(0, ROLE_KIND)
            node = item.data(0, ROLE_NODE)
            if kind == KIND_GROUP and node in self.groups:
                self.groups.remove(node)
            elif kind == KIND_FILE:
                for group in self.groups:
                    if node in group.files:
                        group.files.remove(node)
        self.groups = [g for g in self.groups if g.files]
        self._fill_group_tree()
        self._rebuild_plan()

    def _set_all_events(self, on: bool) -> None:
        for group in self.groups:
            group.make_event = on
        self._fill_group_tree()
        self._rebuild_plan()

    # -- 스위치 그룹 -------------------------------------------------------
    def _load_switch_groups(self) -> None:
        bridge = self.link.bridge
        if bridge is None:
            return
        project = self.project
        self.tasks.run(
            bridge.switch_groups,
            on_done=lambda rows: self._on_switch_groups(rows)
            if self.project is project else None,
            on_fail=lambda msg: log.warning("스위치 조회 실패: %s", msg))

    def _on_switch_groups(self, rows: list[dict]) -> None:
        '''Wwise 에서 읽은 스위치/스테이트 그룹을 받아 둔다.

        읽기는 연결된 뒤에 끝나므로, 그 사이에 이미 스위치 컨테이너를
        골라 둔 묶음이 있을 수 있다. 그 칸은 지금 빈 콤보로 그려져
        있으니 여기서 다시 그리고 이름 맞추기도 돌려 준다.
        '''
        self._switch_lookup = {
            row["path"]: {
                "id": row["id"],
                "type": row.get("type", ""),
                "children": {c["name"]: c["id"] for c in row.get("children", [])},
            }
            for row in rows if row.get("path")
        }
        log.info("스위치/스테이트 그룹 %d개를 읽었습니다.", len(self._switch_lookup))
        waiting = [g for g in self.groups if g.container == "Switch Container"]
        if not waiting:
            return
        for group in waiting:
            self._auto_assign_switches(group)
        self._redraw_tree_soon()

    # -- 계획 --------------------------------------------------------------
    def _queue_replan(self) -> None:
        self._replan_timer.start()

    def _rebuild_plan(self) -> None:
        if not self.groups or not self.destination:
            self.plan = None
            self.issue_list.clear()
            self.import_button.setEnabled(False)
            self.summary_label.setText("")
            self._clear_statuses()
            self._update_paths()
            if self.groups and not self.destination:
                self._show_issues([plan_mod.Issue(
                    "error", "왼쪽 '오디오를 넣을 위치' 에서 임포트할 곳을 고르세요.")])
            return

        self.plan = plan_mod.build(
            self.groups,
            self.destination,
            existing_paths=self._existing_cache,
            import_operation=self.settings.import_operation,
            is_voice=self.settings.is_voice,
            originals_subfolder=self.settings.originals_subfolder,
            destination_segments=self._dest_segments,
            originals_subpath_types=self._subpath_types(),
        )
        self._apply_statuses(self.plan)
        self._show_issues(self.plan.issues)
        self._update_paths()
        self._update_import_enabled()
        self.summary_label.setText(
            f"오디오 {self.plan.file_count} / 컨테이너 {self.plan.container_count} "
            f"/ 이벤트 {self.plan.event_count}")

    def _update_import_enabled(self) -> None:
        """임포트 버튼은 '지금 계획이 실행 가능한가' 하나로만 정한다."""
        plan = self.plan
        self.import_button.setEnabled(
            self.link.is_connected and not self._destination_loading
            and not self._importing and plan is not None
            and not plan.has_errors and not plan.is_empty)

    def _subpath_types(self) -> frozenset[str]:
        """Originals 경로를 계층에 맞춰 만들 때 쓸 타입 집합.

        수동 모드에서는 계층을 따라가지 않으므로 빈 집합을 준다 — 그러면
        ``plan`` 이 자동 경로 계산을 건너뛴다.
        """
        if self.settings.originals_mode == options_dialog.MODE_MANUAL:
            return frozenset()
        return schema.subpath_query_types(self.settings.originals_subpath_keys)

    def _clear_statuses(self) -> None:
        # setText 는 itemChanged 를 낸다. 막지 않으면 우리가 쓴 상태 글자를
        # 사용자가 이름을 고친 것으로 오해한다.
        self.group_tree.blockSignals(True)
        for item in self._walk_rows():
            item.setText(4, "")
        self.group_tree.blockSignals(False)

    def _walk_rows(self):
        """트리의 모든 줄을 훑는다 (최상위 + 자식)."""
        for i in range(self.group_tree.topLevelItemCount()):
            item = self.group_tree.topLevelItem(i)
            yield item
            for j in range(item.childCount()):
                yield item.child(j)

    def _apply_statuses(self, plan: plan_mod.Plan) -> None:
        """계획의 상태를 묶음 트리의 '상태' 열에 반영한다.

        트리를 다시 그리지 않고 열만 갱신한다. 다시 그리면 콤보 위젯이
        새로 만들어지면서 편집 중이던 포커스가 날아간다.

        줄은 두 종류다 — 낱개 파일 줄과 묶음 줄. 둘을 ROLE_KIND 로 가른다.
        """
        # setText/setToolTip 이 itemChanged 를 낸다. 막아 두지 않으면
        # _group_item_changed 가 이것을 사용자 편집으로 보고, 체크박스가 없는
        # 낱개 줄의 checkState(기본 Unchecked)를 읽어 파일을 전부 제외해
        # 버린다. 실제로 "임포트할 파일이 없습니다" 로 나타났던 버그다.
        self.group_tree.blockSignals(True)
        by_container: dict[str, str] = {}
        by_source: dict[Path, tuple[str, str]] = {}
        for node in plan.nodes:
            if node.source is None:
                by_container[node.name.lower()] = node.status
            for sound in _iter_sounds([node]):
                by_source[sound.source] = (sound.status, sound.originals)

        for item in self._walk_rows():
            kind = item.data(0, ROLE_KIND)
            node = item.data(0, ROLE_NODE)
            if node is None:
                continue

            if kind == KIND_GROUP:
                item.setIcon(0, icons.for_token(node.container))
                key = naming.sanitized(node.key).lower()
                self._set_status(item, by_container.get(key, ""))
                continue

            # 파일 줄 — 낱개든 묶음 안이든 같은 방식으로 본다.
            status, originals = by_source.get(node.path, ("", ""))
            self._set_status(item, status)
            if status:
                tip = str(node.path)
                if originals:
                    tip += f"\n  -> Originals\\{originals}"
                item.setToolTip(0, tip)
        self.group_tree.blockSignals(False)

    def _set_status(self, item: QTreeWidgetItem, status: str) -> None:
        item.setText(4, STATUS_LABEL.get(status, ""))
        item.setToolTip(4, STATUS_TOOLTIP.get(status, ""))
        colour = STATUS_COLOR.get(status)
        item.setForeground(4, QBrush(colour) if colour else QBrush())

    def _show_issues(self, issues: list[plan_mod.Issue]) -> None:
        self.issue_list.clear()
        for issue in issues:
            mark = "오류" if issue.level == "error" else "주의"
            item = QTreeWidgetItem(self.issue_list, [mark, issue.message])
            item.setForeground(
                0, QBrush(QColor(220, 90, 90) if issue.level == "error"
                          else QColor(220, 165, 60)))
        if not issues:
            item = QTreeWidgetItem(self.issue_list, ["", "문제 없음"])
            item.setForeground(1, QBrush(QColor(130, 130, 130)))

    # -- 실행 --------------------------------------------------------------
    def _ask_manual_originals(self) -> str | None:
        """수동 모드에서 원본 wav 를 넣을 폴더를 직접 고르게 한다.

        Wwise 의 ``originalsSubFolder`` 는 ``Originals\\<언어>`` 아래의
        **상대 경로**만 받는다. 그래서 고른 폴더를 그 기준으로 상대화하고,
        바깥을 골랐으면 되묻는다.

        취소하면 None 을 돌려주고 임포트를 하지 않는다.
        """
        if self.project is None:
            return None
        language_dir = (Path("Voices") / self.project.default_language
                        if self.settings.is_voice else Path("SFX"))
        base = self.project.originals_root / language_dir
        base.mkdir(parents=True, exist_ok=True)

        chosen = QFileDialog.getExistingDirectory(
            self, "원본 wav 를 넣을 폴더를 고르세요", str(base))
        if not chosen:
            return None
        picked = Path(chosen)
        try:
            relative = picked.relative_to(base)
        except ValueError:
            QMessageBox.warning(
                self, "Easy Sync",
                "Originals 폴더 안쪽을 골라야 합니다.\n\n"
                f"기준: {base}\n고른 곳: {picked}")
            return None
        return "" if str(relative) == "." else str(relative)

    def _do_import(self) -> None:
        if not self.plan or self._destination_loading or self._importing:
            return
        bridge = self._require_wwise()
        if bridge is None:
            return

        if self.settings.originals_mode == options_dialog.MODE_MANUAL:
            subfolder = self._ask_manual_originals()
            if subfolder is None:
                self.status.setText("임포트를 취소했습니다.")
                return
            # 고른 폴더를 계획에 반영한 뒤 그대로 실행한다.
            for entry in self.plan.imports:
                if subfolder:
                    entry["originalsSubFolder"] = subfolder
                else:
                    entry.pop("originalsSubFolder", None)
            for node in _iter_sounds(self.plan.nodes):
                node.originals = subfolder
            self._update_paths()

        self.import_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText("임포트 중...")
        self._importing = True
        self.link.suspend_checks(True)
        self.tasks.run(
            importer.apply,
            bridge,
            self.plan,
            import_operation=self.settings.import_operation,
            language=(self.project.default_language
                      if self.settings.is_voice else schema.LANGUAGE_SFX),
            event_root=self.event_root or self.roots.events_default_wu,
            switch_lookup=self._switch_lookup,
            on_done=self._on_import_done,
            on_fail=self._on_import_failed,
        )

    def _on_import_failed(self, exc) -> None:
        self._importing = False
        self.link.suspend_checks(False)
        self._on_task_failed(exc)

    def _on_import_done(self, result: importer.ImportResult) -> None:
        self._importing = False
        self.link.suspend_checks(False)
        self.progress.setVisible(False)
        self._update_import_enabled()
        self.status.setText(result.summary())
        self._persist()

        # 새로고침을 **먼저** 건다. 아래 알림창은 모달이라 사용자가 닫을
        # 때까지 이벤트 루프를 잡는데, 그 뒤에 새로고침을 걸면 닫기 전까지
        # 화면이 옛 상태로 남는다. 성공이든 실패든 맞춘다 — 실패해도 일부가
        # 만들어졌을 수 있으니 보이는 것이 사실과 같아야 한다.
        self._refresh_after_import()

        if not result.ok:
            QMessageBox.critical(self, "Easy Sync - 임포트 실패", result.error)
        else:
            self._show_result(result)

    def _show_result(self, result: importer.ImportResult) -> None:
        """끝났다는 것을 짧게 알린다.

        긴 로그를 늘어놓지 않는다. 무엇이 몇 개 만들어졌는지와, 문제가
        있었다면 그것만 본다.
        """
        box = QMessageBox(self)
        box.setWindowTitle("Easy Sync — 임포트 완료")
        box.setIcon(QMessageBox.Icon.Warning if result.warnings
                    else QMessageBox.Icon.Information)
        lines = [f"오디오 {result.imported}개"]
        if result.containers:
            lines.append(f"컨테이너 {result.containers}개")
        if result.events:
            lines.append(f"이벤트 {len(result.events)}개")
        if result.switch_assignments:
            lines.append(f"스위치 배정 {result.switch_assignments}개")
        box.setText("만들었습니다 — " + ", ".join(lines))
        box.setInformativeText(f"위치: {self.destination}")
        if result.warnings:
            box.setDetailedText("\n".join(result.warnings))
        reveal = box.addButton("Wwise 에서 보기", QMessageBox.ButtonRole.ActionRole)
        box.addButton("닫기", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        bridge = self.link.bridge
        if box.clickedButton() is reveal and bridge is not None:
            target = bridge.object_at(self.destination)
            if target:
                bridge.reveal(target["id"])

    def _refresh_after_import(self) -> None:
        """임포트 뒤 화면을 Wwise 의 현재 상태로 맞춘다."""
        bridge = self.link.bridge
        if bridge is None:
            return
        if self.destination:
            # 방금 만든 것이 '이미 있음' 으로 보이도록 목적지를 다시 읽는다.
            path, revision = self.destination, self._destination_revision
            self.tasks.run(bridge.existing_paths, path,
                           on_done=lambda rows: self._on_existing_loaded(rows)
                           if (bridge is self.link.bridge and path == self.destination
                               and revision == self._destination_revision) else None)
        # 새로 생긴 컨테이너가 트리에도 나타나야 한다.
        self.audio_panel.reload(self.destination)
        self.event_panel.reload(self.event_root)

    def _on_task_failed(self, exc) -> None:
        """백그라운드 작업이 실패했다.

        연결이 끊긴 것이면 조용히 재접속 상태로 넘긴다 — Wwise 를 닫았을 뿐인데
        오류 창이 뜨면 성가시다. 그 외에는 알린다.
        """
        self.progress.setVisible(False)
        if isinstance(exc, Exception):
            self.link.note_failure(exc)
            if not self.link.is_connected:
                self.import_button.setEnabled(False)
                return
            from .link import _looks_like_disconnect
            if _looks_like_disconnect(exc):
                self.status.setText("요청을 완료하지 못했습니다. Wwise 연결을 확인 중입니다.")
                self._update_import_enabled()
                return
            message = describe_error(exc)
        else:
            message = str(exc)
        self.status.setText("실패")
        # 트리를 펼치다 실패한 것과 계획이 잘못된 것은 다르다. 버튼은
        # 계획 상태로만 정한다 — 예전에는 상관없는 실패 하나가 멀쩡한
        # 계획의 임포트 버튼을 영영 잠갔다.
        self._update_import_enabled()
        QMessageBox.critical(self, "Easy Sync", message)
