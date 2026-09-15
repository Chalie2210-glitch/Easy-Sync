# -*- coding: utf-8 -*-
"""옵션 창.

메인 창에 옵션을 늘어놓지 않는 이유: 한 번 정해 두면 거의 안 바꾸는
값들인데, 늘 보이면 정작 매번 쓰는 것(파일 묶음, 위치 선택)이 밀린다.
메뉴 > 옵션 에서 따로 연다.

여기서 [저장] 을 눌러야 설정 파일에 들어간다. 창을 닫거나 [취소] 하면
아무것도 바뀌지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QRadioButton, QVBoxLayout, QWidget,
)

from . import schema
from .settings import Settings

MODE_SMART = "smart"
MODE_MANUAL = "manual"

IMPORT_OPERATIONS = [
    ("useExisting", "이미 있으면 그대로 둠",
     "같은 이름이 이미 있으면 건드리지 않습니다. 오디오도 다시 넣지 않아서\n"
     "여러 번 눌러도 중복이 생기지 않습니다."),
    ("replaceExisting", "이미 있으면 오디오 교체",
     "오브젝트는 그대로 두고 오디오 소스만 새 파일로 바꿉니다.\n"
     "바운스를 다시 했을 때 씁니다."),
    ("createNew", "항상 새로 만듦 (_01 붙음)",
     "이름이 겹치면 뒤에 _01 을 붙여 새로 만듭니다."),
]


class OptionsDialog(QDialog):
    """설정을 고치는 별도 창."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Easy Sync 옵션")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_originals())
        layout.addWidget(self._build_import())
        layout.addWidget(self._build_defaults())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()
        self._mode_changed()

    # -- 구성 --------------------------------------------------------------
    def _build_originals(self) -> QWidget:
        box = QGroupBox("오리지날 wav 경로")
        layout = QVBoxLayout(box)

        self.smart_radio = QRadioButton("스마트 — Wwise 계층을 따라 자동으로 만듦")
        self.smart_radio.setToolTip(
            "임포트할 위치의 Wwise 계층을 그대로 Originals 폴더로 옮깁니다.\n"
            "아래에서 체크한 종류만 실제 폴더가 됩니다.")
        self.manual_radio = QRadioButton("수동 — 임포트할 때 탐색기로 직접 고름")
        self.manual_radio.setToolTip(
            "임포트를 누르면 폴더 선택 창이 떠서 원본 wav 를 넣을 곳을\n"
            "직접 고릅니다. 계층과 다른 곳에 두고 싶을 때 씁니다.")
        self.smart_radio.toggled.connect(self._mode_changed)
        layout.addWidget(self.smart_radio)
        layout.addWidget(self.manual_radio)

        self.smart_box = QGroupBox("폴더로 만들 계층 종류")
        self.smart_box.setToolTip(
            "체크한 종류만 폴더가 됩니다.\n"
            "보통 Work Unit·폴더·액터믹서는 정리 구조라 폴더로 만들고,\n"
            "랜덤/스위치 컨테이너는 재생 구조라 만들지 않습니다.")
        smart_layout = QVBoxLayout(self.smart_box)

        self.subpath_checks: dict[str, QCheckBox] = {}
        columns = QHBoxLayout()
        column = QVBoxLayout()
        for index, (key, label, _types) in enumerate(schema.ORIGINALS_SUBPATH_TYPES):
            check = QCheckBox(label)
            check.setToolTip(f"'{label}' 계층을 Originals 폴더로도 만듭니다.")
            self.subpath_checks[key] = check
            column.addWidget(check)
            if index in (2, 5):
                columns.addLayout(column)
                column = QVBoxLayout()
        column.addStretch(1)
        columns.addLayout(column)
        smart_layout.addLayout(columns)

        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("기준 폴더:"))
        self.base_folder = QLineEdit()
        self.base_folder.setPlaceholderText("비워도 됨")
        self.base_folder.setToolTip(
            "계층 경로 앞에 항상 붙는 고정 폴더입니다.\n"
            "예: 'Game' 을 넣으면 Originals\\SFX\\Game\\... 이 됩니다.")
        base_row.addWidget(self.base_folder, 1)
        smart_layout.addLayout(base_row)
        layout.addWidget(self.smart_box)

        self.manual_hint = QLabel(
            "임포트를 누르면 폴더 선택 창이 뜹니다. Originals 안쪽을 고르세요.\n"
            "바깥을 고르면 Wwise 가 파일을 Originals 로 복사해 옵니다.")
        self.manual_hint.setWordWrap(True)
        self.manual_hint.setStyleSheet("color: #8a8a8a;")
        layout.addWidget(self.manual_hint)
        return box

    def _build_import(self) -> QWidget:
        box = QGroupBox("임포트")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("이미 있을 때:"))
        self.op_box = QComboBox()
        for value, label, tip in IMPORT_OPERATIONS:
            self.op_box.addItem(label, value)
            self.op_box.setItemData(self.op_box.count() - 1, tip,
                                    Qt.ItemDataRole.ToolTipRole)
        self.op_box.currentIndexChanged.connect(self._op_changed)
        row.addWidget(self.op_box, 1)
        layout.addLayout(row)

        self.voice_check = QCheckBox("보이스로 임포트")
        self.voice_check.setToolTip(
            "켜면 Sound Voice 로 임포트하고 원본이 언어별 폴더\n"
            "(Originals\\Voices\\<언어>)로 들어갑니다.")
        layout.addWidget(self.voice_check)
        return box

    def _build_defaults(self) -> QWidget:
        box = QGroupBox("묶기")
        outer = QVBoxLayout(box)

        self.auto_group = QCheckBox("가져올 때 이름이 비슷한 파일을 자동으로 묶기")
        self.auto_group.setToolTip(
            "파일 이름의 끝 번호를 보고 묶습니다.\n"
            "예: Creature_SFX_01/02/03 -> Creature_SFX 컨테이너 하나\n\n"
            "꺼 두면 가져온 그대로 낱개로 들어오고, 필요한 것만 골라\n"
            "우클릭으로 묶습니다. 자동 묶기는 이름만 보고 하는 추측이라\n"
            "기본은 꺼져 있습니다.")
        outer.addWidget(self.auto_group)

        layout = QHBoxLayout()
        outer.addLayout(layout)
        layout.addWidget(QLabel("묶였을 때 컨테이너:"))
        self.container_box = QComboBox()
        self.container_box.addItem("컨테이너 없음", schema.NO_CONTAINER)
        for token, label in schema.GROUP_CONTAINERS:
            self.container_box.addItem(label, token)
        self.container_box.setToolTip(
            "파일을 새로 가져왔을 때 묶음에 기본으로 붙는 컨테이너 종류입니다.")
        layout.addWidget(self.container_box, 1)

        self.default_event = QCheckBox("이벤트 자동 체크")
        self.default_event.setToolTip(
            "새 묶음의 '이벤트' 칸을 기본으로 켜 둡니다.")
        layout.addWidget(self.default_event)
        return box

    # -- 동작 --------------------------------------------------------------
    def _mode_changed(self) -> None:
        smart = self.smart_radio.isChecked()
        self.smart_box.setVisible(smart)
        self.manual_hint.setVisible(not smart)
        self.adjustSize()

    def _op_changed(self) -> None:
        self.op_box.setToolTip(
            self.op_box.itemData(self.op_box.currentIndex(),
                                 Qt.ItemDataRole.ToolTipRole) or "")

    def _load(self) -> None:
        s = self.settings
        (self.manual_radio if s.originals_mode == MODE_MANUAL
         else self.smart_radio).setChecked(True)
        for key, check in self.subpath_checks.items():
            check.setChecked(key in s.originals_subpath_keys)
        self.base_folder.setText(s.originals_subfolder)
        index = self.op_box.findData(s.import_operation)
        if index >= 0:
            self.op_box.setCurrentIndex(index)
        self._op_changed()
        self.voice_check.setChecked(s.is_voice)
        index = self.container_box.findData(s.default_container)
        if index >= 0:
            self.container_box.setCurrentIndex(index)
        self.default_event.setChecked(s.default_make_event)
        self.auto_group.setChecked(s.auto_group)

    def _save(self) -> None:
        s = self.settings
        s.originals_mode = MODE_SMART if self.smart_radio.isChecked() else MODE_MANUAL
        s.originals_subpath_keys = [
            key for key, check in self.subpath_checks.items() if check.isChecked()]
        s.originals_subfolder = self.base_folder.text().strip()
        s.import_operation = self.op_box.currentData()
        s.is_voice = self.voice_check.isChecked()
        s.default_container = self.container_box.currentData()
        s.default_make_event = self.default_event.isChecked()
        s.auto_group = self.auto_group.isChecked()
        s.save()
        self.accept()
