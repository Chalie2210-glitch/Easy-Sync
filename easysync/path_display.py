"""Selectable path text that wraps long segments and scrolls when necessary."""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextEdit


class PathDisplay(QTextEdit):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self.setText(text)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)
        self.setToolTip(text)
        self._fit_height()

    def _fit_height(self, *_):
        layout = self.document().firstBlock().layout()
        line = (layout.lineAt(0).height() if layout.lineCount()
                else self.fontMetrics().lineSpacing())
        margin = self.document().documentMargin()
        # Stop exactly before line five; extra bottom padding would show a
        # clipped sliver of that line in a scrollable viewport.
        wanted = math.ceil(max(line + 2 * margin,
                               min(self.document().size().height(), 4 * line + margin)))
        if self.minimumHeight() != wanted or self.maximumHeight() != wanted:
            self.setFixedHeight(wanted)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()
