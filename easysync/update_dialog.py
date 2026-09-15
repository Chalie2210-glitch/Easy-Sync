"""User-initiated update flow. Never runs during a Wwise import."""
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from . import updates
from .tasks import TaskRunner
from .version import VERSION, RELEASES_URL


class UpdateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Easy Sync 업데이트")
        self.setMinimumWidth(430)
        self.tasks = TaskRunner()
        self.busy = False
        self.release = None
        self.installer = None
        layout = QVBoxLayout(self)
        self.label = QLabel(f"현재 버전: {VERSION}\n업데이트 확인을 눌러 새 버전을 확인하세요.")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.action = QPushButton("업데이트 확인")
        self.action.clicked.connect(self._act)
        layout.addWidget(self.action)
        releases = QPushButton("GitHub 릴리스 보기")
        releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        layout.addWidget(releases)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def _act(self):
        if self.busy:
            return
        if self.installer:
            # Installer waits for the GUI's named mutex; never forces a Wwise import to stop.
            try:
                subprocess.Popen([str(self.installer), "/NORESTART"], close_fds=True)
            except OSError as exc:
                self._failed(str(exc))
                return
            self.accept()
            return
        self.busy = True
        self.action.setEnabled(False)
        if self.release:
            self.label.setText("설치 파일을 다운로드하고 SHA-256을 검증하고 있습니다…")
            self.tasks.run(updates.download, self.release, on_done=self._downloaded, on_fail=self._failed)
        else:
            self.label.setText("GitHub에서 최신 버전을 확인하고 있습니다…")
            self.tasks.run(updates.check_latest, on_done=self._checked, on_fail=self._failed)

    def _checked(self, release):
        self.busy = False
        self.action.setEnabled(True)
        if release is None:
            self.label.setText(f"현재 버전 {VERSION}은 최신 버전입니다.")
        elif not getattr(sys, "frozen", False):
            self.label.setText(f"새 버전 {release.version}이 있습니다. 소스 실행 환경에서는 GitHub 릴리스를 이용하세요.")
        else:
            self.release = release
            self.label.setText(f"새 버전 {release.version}\n다운로드: {release.size / 1024 / 1024:.1f} MB\n설정과 즐겨찾기는 유지됩니다.")
            self.action.setText("업데이트 다운로드")

    def _downloaded(self, path: Path):
        self.busy = False
        self.installer = path
        self.action.setEnabled(True)
        self.action.setText("Easy Sync 종료 후 설치")
        self.label.setText("다운로드 검증이 완료되었습니다. 설치를 누르면 Easy Sync를 종료하고 설치 프로그램을 엽니다.")

    def _failed(self, message):
        self.busy = False
        self.action.setEnabled(True)
        self.label.setText(f"업데이트를 완료하지 못했습니다. 기존 프로그램은 그대로 사용할 수 있습니다.\n\n{message}")
