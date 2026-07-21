import os
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QLabel, QStackedWidget,
    QFileDialog, QMessageBox, QToolBar, QStatusBar,
)

import jsonc
import xmlmodel
import registry
from json_tree_widget import JsonTreeEditor
from xml_tree_widget import XmlTreeEditor
from raw_editor import RawEditor

APP_TITLE = "Config GUI"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 750)

        self.current_path = None
        self.current_format = None
        self.doc = None
        self.dirty = False
        self.view_mode = "form"  # 'form' | 'raw'
        self._loading = False

        self._build_ui()
        self._refresh_sidebar()
        self._update_title()

    # ---- UI construction --------------------------------------------

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        splitter.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        right_layout.addWidget(self.path_label)

        self.stack = QStackedWidget()
        self.empty_label = QLabel(
            "Pick a detected config on the left, or load one manually below.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: palette(mid);")
        self.stack.addWidget(self.empty_label)          # index 0

        self.json_editor = JsonTreeEditor()
        self.json_editor.changed.connect(self._on_structured_changed)
        self.stack.addWidget(self.json_editor)           # index 1

        self.xml_editor = XmlTreeEditor()
        self.xml_editor.changed.connect(self._on_structured_changed)
        self.stack.addWidget(self.xml_editor)             # index 2

        self.raw_editor = RawEditor()
        self.raw_editor.contentChanged.connect(self._on_raw_changed)
        self.stack.addWidget(self.raw_editor)              # index 3

        right_layout.addWidget(self.stack)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._build_toolbar()
        self.setStatusBar(QStatusBar())

    def _build_sidebar(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(QLabel("<b>Detected configs</b>"))
        self.shortcut_list = QListWidget()
        self.shortcut_list.itemActivated.connect(self._on_shortcut_activated)
        layout.addWidget(self.shortcut_list)

        refresh_btn = QPushButton("Rescan")
        refresh_btn.clicked.connect(self._refresh_sidebar)
        layout.addWidget(refresh_btn)

        layout.addWidget(QLabel("<b>Open manually</b>"))
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/path/to/config")
        self.path_edit.returnPressed.connect(self._on_manual_load_clicked)
        path_row.addWidget(self.path_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_clicked)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_manual_load_clicked)
        layout.addWidget(load_btn)

        layout.addStretch(1)
        panel.setMaximumWidth(320)
        return panel

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._on_save)
        tb.addAction(save_action)

        save_as_action = QAction("Save As…", self)
        save_as_action.triggered.connect(self._on_save_as)
        tb.addAction(save_as_action)

        reload_action = QAction("Reload", self)
        reload_action.triggered.connect(self._on_reload)
        tb.addAction(reload_action)

        tb.addSeparator()

        self.toggle_action = QAction("Switch to code editor", self)
        self.toggle_action.triggered.connect(self._on_toggle_view)
        tb.addAction(self.toggle_action)

    # ---- sidebar / loading --------------------------------------------

    def _refresh_sidebar(self):
        self.shortcut_list.clear()
        for entry in registry.discover():
            item = QListWidgetItem(f"{entry['label']}\n{entry['path']}")
            item.setData(Qt.UserRole, entry)
            self.shortcut_list.addItem(item)
        if self.shortcut_list.count() == 0:
            item = QListWidgetItem("(none of the common configs were found)")
            item.setFlags(Qt.NoItemFlags)
            self.shortcut_list.addItem(item)

    def _on_shortcut_activated(self, item):
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        self.load_file(entry["path"], fmt=entry["format"])

    def _on_browse_clicked(self):
        start_dir = os.path.expanduser("~/.config")
        path, _ = QFileDialog.getOpenFileName(self, "Open config file", start_dir)
        if path:
            self.path_edit.setText(path)
            self.load_file(path)

    def _on_manual_load_clicked(self):
        path = self.path_edit.text().strip()
        if not path:
            return
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Not found", f"No such file:\n{path}")
            return
        self.load_file(path)

    # ---- core load/save --------------------------------------------

    def load_file(self, path, fmt=None):
        if not self._confirm_discard_if_dirty():
            return
        fmt = fmt or registry.guess_format(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not read file:\n{e}")
            return

        self._loading = True
        try:
            self.current_path = path
            self.current_format = fmt
            self.raw_editor.set_language(fmt)

            if fmt in ("jsonc", "json"):
                try:
                    self.doc = jsonc.parse(text)
                except jsonc.JsoncError as e:
                    QMessageBox.warning(
                        self, "Parse error",
                        f"Couldn't parse this as JSON(C), opening in the raw code "
                        f"editor instead.\n\n{e}")
                    self.doc = None
                    self.current_format = fmt = "text"
                else:
                    self.json_editor.load(self.doc, root_label=os.path.basename(path))
            elif fmt == "xml":
                try:
                    self.doc = xmlmodel.parse(text)
                except ET.ParseError as e:
                    QMessageBox.warning(
                        self, "Parse error",
                        f"Couldn't parse this as XML, opening in the raw code "
                        f"editor instead.\n\n{e}")
                    self.doc = None
                    self.current_format = fmt = "text"
                else:
                    self.xml_editor.load(self.doc)

            self.raw_editor.set_text(text)

            structured_available = fmt in ("jsonc", "json", "xml")
            self.view_mode = "form" if structured_available else "raw"
            self._apply_view_mode()
            self.toggle_action.setEnabled(structured_available)

            self.dirty = False
            self._update_title()
        finally:
            self._loading = False

    def _apply_view_mode(self):
        if self.view_mode == "raw":
            self.stack.setCurrentWidget(self.raw_editor)
            self.toggle_action.setText("Switch to form editor")
        elif self.current_format in ("jsonc", "json"):
            self.stack.setCurrentWidget(self.json_editor)
            self.toggle_action.setText("Switch to code editor")
        elif self.current_format == "xml":
            self.stack.setCurrentWidget(self.xml_editor)
            self.toggle_action.setText("Switch to code editor")
        else:
            self.stack.setCurrentWidget(self.empty_label)

    def _on_toggle_view(self):
        if self.current_path is None:
            return
        if self.view_mode == "form":
            self.raw_editor.set_text(self.doc.serialize())
            self.view_mode = "raw"
        else:
            text = self.raw_editor.text()
            try:
                if self.current_format in ("jsonc", "json"):
                    new_doc = jsonc.parse(text)
                else:
                    new_doc = xmlmodel.parse(text)
            except (jsonc.JsoncError, ET.ParseError) as e:
                QMessageBox.warning(self, "Syntax error",
                                     f"Can't switch back to the form editor until this "
                                     f"is fixed:\n\n{e}")
                return
            self.doc = new_doc
            if self.current_format in ("jsonc", "json"):
                self.json_editor.load(self.doc, root_label=os.path.basename(self.current_path))
            else:
                self.xml_editor.load(self.doc)
            self.view_mode = "form"
        self._apply_view_mode()

    def _on_structured_changed(self):
        if self._loading:
            return
        self.dirty = True
        self._update_title()

    def _on_raw_changed(self):
        if self._loading:
            return
        self.dirty = True
        self._update_title()

    def _on_save(self):
        if self.current_path is None:
            return
        if self.view_mode == "raw":
            text = self.raw_editor.text()
            if self.current_format in ("jsonc", "json"):
                try:
                    self.doc = jsonc.parse(text)
                except jsonc.JsoncError as e:
                    if not self._confirm_save_anyway(e):
                        return
            elif self.current_format == "xml":
                try:
                    self.doc = xmlmodel.parse(text)
                except ET.ParseError as e:
                    if not self._confirm_save_anyway(e):
                        return
        else:
            text = self.doc.serialize()

        try:
            with open(self.current_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not save file:\n{e}")
            return

        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.current_path}", 3000)

    def _confirm_save_anyway(self, error):
        resp = QMessageBox.warning(
            self, "Syntax error",
            f"This doesn't parse as valid {self.current_format.upper()}:\n\n{error}\n\n"
            f"Save the raw text anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def _on_save_as(self):
        if self.current_path is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save As", self.current_path)
        if not path:
            return
        self.current_path = path
        self._on_save()
        self._update_title()

    def _on_reload(self):
        if self.current_path is None:
            return
        if self.dirty:
            resp = QMessageBox.question(
                self, "Reload", "Discard unsaved changes and reload from disk?")
            if resp != QMessageBox.Yes:
                return
        self.load_file(self.current_path, fmt=self.current_format)

    # ---- misc -----------------------------------------------------------

    def _update_title(self):
        if self.current_path is None:
            self.setWindowTitle(APP_TITLE)
            self.path_label.setText("No file loaded")
            return
        star = "*" if self.dirty else ""
        self.setWindowTitle(f"{star}{os.path.basename(self.current_path)} — {APP_TITLE}")
        suffix = "  (unsaved changes)" if self.dirty else ""
        self.path_label.setText(self.current_path + suffix)

    def _confirm_discard_if_dirty(self):
        if not self.dirty:
            return True
        resp = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Discard them and continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return resp == QMessageBox.Yes

    def closeEvent(self, event):
        if self._confirm_discard_if_dirty():
            event.accept()
        else:
            event.ignore()
