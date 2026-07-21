"""Structured tree editor for xmlmodel.XmlDocument trees (labwc/openbox
rc.xml, menu.xml, ...).

Elements are addressed by a path of child indices from the root (comments
are just children with tag is ET.Comment, so they show up in the tree too
and can be edited/deleted like anything else).
"""
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QMenu, QDialog, QDialogButtonBox, QMessageBox, QSplitter, QLabel, QComboBox,
)

import xmlmodel as xm


def _preview(el):
    if xm.is_comment(el):
        return (el.text or "").strip()
    if xm.is_pi(el):
        return el.text or ""
    attrs = " ".join(f'{k}="{v}"' for k, v in el.attrib.items())
    text = (el.text or "").strip()
    parts = [p for p in (attrs, text) if p]
    return "  ".join(parts)


def get_element(root, path):
    node = root
    for idx in path:
        node = list(node)[idx]
    return node


class AddNodeDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add node")
        form = QFormLayout(self)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["element", "comment"])
        form.addRow("Kind:", self.kind_combo)
        self.tag_edit = QLineEdit()
        form.addRow("Tag name:", self.tag_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class XmlTreeEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self._expanded_paths = set()
        self._current_path = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Tag", "Attributes / Text"])
        self.tree.setColumnWidth(0, 220)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        splitter.addWidget(self.tree)

        detail_panel = QWidget()
        form = QFormLayout(detail_panel)

        self.tag_edit = QLineEdit()
        self.tag_edit.editingFinished.connect(self._apply_tag)
        form.addRow("Tag:", self.tag_edit)

        self.attr_table = QTableWidget(0, 2)
        self.attr_table.setHorizontalHeaderLabels(["Attribute", "Value"])
        self.attr_table.horizontalHeader().setStretchLastSection(True)
        self.attr_table.itemChanged.connect(self._on_attr_item_changed)
        form.addRow("Attributes:", self.attr_table)

        attr_btns = QHBoxLayout()
        self.add_attr_btn = QPushButton("Add attribute")
        self.add_attr_btn.clicked.connect(self._add_attribute)
        self.del_attr_btn = QPushButton("Remove attribute")
        self.del_attr_btn.clicked.connect(self._remove_attribute)
        attr_btns.addWidget(self.add_attr_btn)
        attr_btns.addWidget(self.del_attr_btn)
        attr_btns.addStretch(1)
        form.addRow("", attr_btns)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setMaximumHeight(80)
        self.text_edit.textChanged.connect(self._apply_text)
        form.addRow("Text:", self.text_edit)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add child…")
        self.add_btn.clicked.connect(self._add_child)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self._set_detail_enabled(False)
        self._suspend_attr_signal = False

    # ---- loading / building --------------------------------------------

    def load(self, doc):
        self.doc = doc
        self._expanded_paths = set()
        self._current_path = None
        self._rebuild()

    def _rebuild(self, select_path=None):
        prev_expanded = set(self._expanded_paths)
        self.tree.clear()
        if self.doc is None:
            return
        root_item = self._build_item(None, self.doc.root, ())
        self.tree.addTopLevelItem(root_item)
        self._restore_expansion(root_item, prev_expanded)
        root_item.setExpanded(True)
        if select_path is not None:
            item = self._find_item(root_item, select_path)
            if item is not None:
                self.tree.setCurrentItem(item)

    def _build_item(self, parent_item, el, path):
        item = QTreeWidgetItem([xm.tag_label(el), _preview(el)])
        item.setData(0, Qt.UserRole, path)
        for i, child in enumerate(list(el)):
            self._build_item(item, child, path + (i,))
        if parent_item is not None:
            parent_item.addChild(item)
        return item

    def _find_item(self, item, path):
        if item.data(0, Qt.UserRole) == path:
            return item
        for i in range(item.childCount()):
            found = self._find_item(item.child(i), path)
            if found is not None:
                return found
        return None

    def _restore_expansion(self, item, expanded_paths):
        path = item.data(0, Qt.UserRole)
        if path in expanded_paths or path == ():
            item.setExpanded(True)
        for i in range(item.childCount()):
            self._restore_expansion(item.child(i), expanded_paths)

    def _on_expanded(self, item):
        self._expanded_paths.add(item.data(0, Qt.UserRole))

    def _on_collapsed(self, item):
        self._expanded_paths.discard(item.data(0, Qt.UserRole))

    # ---- selection / detail panel ---------------------------------------

    def _set_detail_enabled(self, enabled):
        for w in (self.tag_edit, self.attr_table, self.text_edit,
                   self.add_attr_btn, self.del_attr_btn, self.delete_btn):
            w.setEnabled(enabled)

    def _on_selection_changed(self):
        items = self.tree.selectedItems()
        if not items:
            self._current_path = None
            self._set_detail_enabled(False)
            return
        path = items[0].data(0, Qt.UserRole)
        self._current_path = path
        self._set_detail_enabled(True)
        el = get_element(self.doc.root, path)
        is_special = xm.is_comment(el) or xm.is_pi(el)

        self.tag_edit.setEnabled(not is_special)
        self.tag_edit.blockSignals(True)
        self.tag_edit.setText("" if is_special else el.tag)
        self.tag_edit.blockSignals(False)

        self.attr_table.setEnabled(not is_special)
        self.add_attr_btn.setEnabled(not is_special)
        self.del_attr_btn.setEnabled(not is_special)
        self.delete_btn.setEnabled(path != ())

        self._suspend_attr_signal = True
        self.attr_table.setRowCount(0)
        if not is_special:
            for k, v in el.attrib.items():
                row = self.attr_table.rowCount()
                self.attr_table.insertRow(row)
                self.attr_table.setItem(row, 0, QTableWidgetItem(k))
                self.attr_table.setItem(row, 1, QTableWidgetItem(v))
        self._suspend_attr_signal = False

        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(el.text or "")
        self.text_edit.blockSignals(False)

    # ---- editing ----------------------------------------------------

    def _apply_tag(self):
        path = self._current_path
        if path is None or not self.tag_edit.isEnabled():
            return
        el = get_element(self.doc.root, path)
        new_tag = self.tag_edit.text().strip()
        if new_tag and new_tag != el.tag:
            el.tag = new_tag
            self.changed.emit()
            item = self.tree.currentItem()
            if item is not None:
                item.setText(0, xm.tag_label(el))

    def _on_attr_item_changed(self, _item):
        if self._suspend_attr_signal:
            return
        path = self._current_path
        if path is None:
            return
        el = get_element(self.doc.root, path)
        new_attrib = {}
        for row in range(self.attr_table.rowCount()):
            name_item = self.attr_table.item(row, 0)
            value_item = self.attr_table.item(row, 1)
            name = (name_item.text().strip() if name_item else "")
            value = (value_item.text() if value_item else "")
            if name:
                new_attrib[name] = value
        el.attrib.clear()
        el.attrib.update(new_attrib)
        self.changed.emit()
        item = self.tree.currentItem()
        if item is not None:
            item.setText(1, _preview(el))

    def _add_attribute(self):
        if self._current_path is None:
            return
        row = self.attr_table.rowCount()
        self.attr_table.insertRow(row)
        self.attr_table.setItem(row, 0, QTableWidgetItem("name"))
        self.attr_table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_attribute(self):
        row = self.attr_table.currentRow()
        if row < 0:
            return
        self.attr_table.removeRow(row)
        self._on_attr_item_changed(None)

    def _apply_text(self):
        path = self._current_path
        if path is None:
            return
        el = get_element(self.doc.root, path)
        new_text = self.text_edit.toPlainText()
        el.text = new_text if new_text else (None if not xm.is_comment(el) else " ")
        self.changed.emit()
        item = self.tree.currentItem()
        if item is not None:
            item.setText(0 if xm.is_comment(el) else 1,
                         xm.tag_label(el) if xm.is_comment(el) else _preview(el))

    # ---- add / delete -------------------------------------------------

    def _add_child(self):
        path = self._current_path
        if path is None:
            return
        el = get_element(self.doc.root, path)
        if xm.is_comment(el) or xm.is_pi(el):
            QMessageBox.information(self, "Not a container", "Select an element to add a child to it.")
            return
        dlg = AddNodeDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.kind_combo.currentText() == "comment":
            new_el = xm.new_comment(" comment ")
        else:
            tag = dlg.tag_edit.text().strip()
            if not tag:
                QMessageBox.warning(self, "Missing tag", "Enter a tag name.")
                return
            new_el = xm.new_element(tag)
        el.append(new_el)
        self.changed.emit()
        self._rebuild(select_path=path + (len(list(el)) - 1,))

    def _delete_selected(self):
        path = self._current_path
        if not path:
            return
        el = get_element(self.doc.root, path)
        label = el.tag if not (xm.is_comment(el) or xm.is_pi(el)) else xm.tag_label(el)
        resp = QMessageBox.question(self, "Delete", f"Delete {label!r} and everything inside it?")
        if resp != QMessageBox.Yes:
            return
        parent = get_element(self.doc.root, path[:-1])
        parent.remove(el)
        self.changed.emit()
        self._rebuild(select_path=path[:-1])

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        path = item.data(0, Qt.UserRole)
        el = get_element(self.doc.root, path)
        menu = QMenu(self)
        if not (xm.is_comment(el) or xm.is_pi(el)):
            menu.addAction("Add child…", self._add_child)
        if path != ():
            menu.addAction("Delete", self._delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
