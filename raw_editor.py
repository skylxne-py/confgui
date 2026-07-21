"""A lightweight raw text/code editor widget: a plain monospace QPlainTextEdit
with minimal JSON/XML syntax highlighting. This is the fallback "edit anything
by hand" view when the structured GUI can't (or shouldn't) model something.
"""
from PySide6.QtCore import Qt, QRegularExpression, Signal
from PySide6.QtGui import (
    QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QFontDatabase,
)
from PySide6.QtWidgets import QPlainTextEdit


def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class JsoncHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = [
            (QRegularExpression(r'"(?:\\.|[^"\\])*"\s*(?=:)'), _fmt("#8fb2e6", bold=True)),  # keys
            (QRegularExpression(r'"(?:\\.|[^"\\])*"'), _fmt("#b5cea8")),  # strings
            (QRegularExpression(r'\b-?\d+(?:\.\d+)?\b'), _fmt("#d19a66")),  # numbers
            (QRegularExpression(r'\b(true|false|null)\b'), _fmt("#c586c0")),
            (QRegularExpression(r'//[^\n]*'), _fmt("#6a9955", italic=True)),
        ]
        self.block_comment_start = QRegularExpression(r"/\*")
        self.block_comment_end = QRegularExpression(r"\*/")
        self.comment_fmt = _fmt("#6a9955", italic=True)

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != 1:
            m = self.block_comment_start.match(text)
            start = m.capturedStart() if m.hasMatch() else -1
        while start >= 0:
            m_end = self.block_comment_end.match(text, start)
            if m_end.hasMatch():
                end = m_end.capturedEnd()
                self.setFormat(start, end - start, self.comment_fmt)
                m = self.block_comment_start.match(text, end)
                start = m.capturedStart() if m.hasMatch() else -1
            else:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.comment_fmt)
                start = -1


class XmlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = [
            (QRegularExpression(r"</?[A-Za-z0-9_:\-]+"), _fmt("#8fb2e6", bold=True)),
            (QRegularExpression(r"[A-Za-z0-9_:\-]+(?==)"), _fmt("#d19a66")),
            (QRegularExpression(r'"[^"]*"'), _fmt("#b5cea8")),
            (QRegularExpression(r"<!--.*?-->"), _fmt("#6a9955", italic=True)),
            (QRegularExpression(r"[/?]?>"), _fmt("#8fb2e6", bold=True)),
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class RawEditor(QPlainTextEdit):
    contentChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(font.pointSize() + 1)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._highlighter = None
        self.textChanged.connect(self.contentChanged.emit)

    def set_language(self, fmt):
        self._highlighter = None  # drop old one so it detaches from the doc
        if fmt in ("jsonc", "json"):
            self._highlighter = JsoncHighlighter(self.document())
        elif fmt == "xml":
            self._highlighter = XmlHighlighter(self.document())

    def set_text(self, text):
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)

    def text(self):
        return self.toPlainText()
