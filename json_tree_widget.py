"""Structured tree editor for jsonc.JsoncDocument trees (Waybar config etc).

Left/top: a 3-column QTreeWidget (Key, Value, Type) built from the document.
Bottom: a details panel to edit the selected node's key/type/value with plain
widgets (line edits, a checkbox, a combo box) - not a code editor. Containers
(objects/arrays) are edited by adding/deleting children via the tree's
context menu or the toolbar buttons.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel, QStackedWidget,
    QMenu, QDialog, QDialogButtonBox, QMessageBox, QSplitter,
)

import jsonc

SCALAR_TYPES = ["string", "number", "boolean", "null"]
ALL_TYPES = SCALAR_TYPES + ["object", "array"]


def _short(pyval):
    if isinstance(pyval, str):
        s = pyval
        return s if len(s) <= 60 else s[:57] + "..."
    return repr(pyval)


class AddChildDialog(QDialog):
    def __init__(self, parent, is_object):
        super().__init__(parent)
        self.is_object = is_object
        self.setWindowTitle("Add key" if is_object else "Add item")
        form = QFormLayout(self)

        self.key_edit = QLineEdit()
        if is_object:
            form.addRow("Key:", self.key_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(ALL_TYPES)
        form.addRow("Type:", self.type_combo)

        self.value_edit = QLineEdit()
        self.value_edit.setText("")
        form.addRow("Initial value:", self.value_edit)
        self.type_combo.currentTextChanged.connect(self._sync_value_enabled)
        self._sync_value_enabled(self.type_combo.currentText())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_value_enabled(self, type_name):
        self.value_edit.setEnabled(type_name in ("string", "number"))
        if type_name == "boolean":
            self.value_edit.setText("false")
        elif type_name == "null":
            self.value_edit.setText("null")
        elif type_name in ("object", "array"):
            self.value_edit.setText("{}" if type_name == "object" else "[]")

    def result_value(self):
        t = self.type_combo.currentText()
        if t == "object":
            return jsonc.EMPTY_OBJECT
        if t == "array":
            return jsonc.EMPTY_ARRAY
        if t == "boolean":
            return self.value_edit.text().strip().lower() in ("true", "1", "yes")
        if t == "null":
            return None
        if t == "number":
            text = self.value_edit.text().strip() or "0"
            try:
                return int(text)
            except ValueError:
                return float(text)
        return self.value_edit.text()

    def result_key(self):
        return self.key_edit.text().strip()


class JsonTreeEditor(QWidget):
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
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Key", "Value", "Type"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 260)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        splitter.addWidget(self.tree)

        detail_panel = QWidget()
        form = QFormLayout(detail_panel)

        self.key_edit = QLineEdit()
        self.key_edit.editingFinished.connect(self._apply_key)
        form.addRow("Key:", self.key_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(ALL_TYPES)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Type:", self.type_combo)

        self.value_stack = QStackedWidget()
        self.value_line = QLineEdit()
        self.value_line.editingFinished.connect(self._apply_value)
        self.value_check = QCheckBox("true")
        self.value_check.toggled.connect(self._apply_value)
        self.value_null_label = QLabel("null")
        self.value_container_label = QLabel("(edit children in the tree above)")
        self.value_stack.addWidget(self.value_line)       # 0 string/number
        self.value_stack.addWidget(self.value_check)       # 1 boolean
        self.value_stack.addWidget(self.value_null_label)  # 2 null
        self.value_stack.addWidget(self.value_container_label)  # 3 object/array
        form.addRow("Value:", self.value_stack)

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

    # ---- loading / building -------------------------------------------

    def load(self, doc, root_label="root"):
        self.doc = doc
        self._root_label = root_label
        self._expanded_paths = set()
        self._current_path = None
        self._rebuild()

    def _rebuild(self, select_path=None):
        prev_expanded = set(self._expanded_paths)
        self.tree.clear()
        if self.doc is None:
            return
        root_item = self._build_item(None, self.doc.root, (), self._root_label)
        self.tree.addTopLevelItem(root_item)
        self._restore_expansion(root_item, prev_expanded)
        root_item.setExpanded(True)
        if select_path is not None:
            item = self._find_item(root_item, select_path)
            if item is not None:
                self.tree.setCurrentItem(item)

    def _build_item(self, parent_item, node, path, label):
        item = QTreeWidgetItem([label, "", ""])
        item.setData(0, Qt.UserRole, path)
        if isinstance(node, jsonc.ObjNode):
            item.setText(1, f"{{...}}  ({len(node.members)} keys)")
            item.setText(2, "object")
            for m in node.members:
                self._build_item(item, m.value, path + (m.key,), m.key)
        elif isinstance(node, jsonc.ArrNode):
            item.setText(1, f"[...]  ({len(node.items)} items)")
            item.setText(2, "array")
            for i, it in enumerate(node.items):
                self._build_item(item, it.value, path + (i,), f"[{i}]")
        else:
            item.setText(1, _short(node.value()))
            item.setText(2, node.type_name())
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

    # ---- selection / detail panel --------------------------------------

    def _set_detail_enabled(self, enabled):
        for w in (self.key_edit, self.type_combo, self.value_line,
                   self.value_check, self.delete_btn):
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
        is_root = (path == ())
        self.delete_btn.setEnabled(not is_root)

        node = jsonc.get_node(self.doc, path)
        if is_root:
            self.key_edit.setText(self._root_label)
        else:
            key = path[-1]
            self.key_edit.setText(str(key) if isinstance(key, str) else f"[{key}]")

        self.type_combo.blockSignals(True)
        if isinstance(node, jsonc.ObjNode):
            self.type_combo.setCurrentText("object")
            self.value_stack.setCurrentWidget(self.value_container_label)
        elif isinstance(node, jsonc.ArrNode):
            self.type_combo.setCurrentText("array")
            self.value_stack.setCurrentWidget(self.value_container_label)
        else:
            self.type_combo.setCurrentText(node.type_name())
            self._show_scalar_value(node)
        self.type_combo.blockSignals(False)

        # Array items have no editable key (positional).
        parent_is_array = len(path) > 0 and isinstance(
            jsonc.get_node(self.doc, path[:-1]), jsonc.ArrNode)
        self.key_edit.setEnabled(not is_root and not parent_is_array)

    def _show_scalar_value(self, node):
        t = node.type_name()
        if t == "boolean":
            self.value_stack.setCurrentWidget(self.value_check)
            self.value_check.blockSignals(True)
            self.value_check.setChecked(node.value())
            self.value_check.blockSignals(False)
        elif t == "null":
            self.value_stack.setCurrentWidget(self.value_null_label)
        else:
            self.value_stack.setCurrentWidget(self.value_line)
            self.value_line.setText(str(node.value()))

    # ---- editing ---------------------------------------------------------

    def _apply_key(self):
        path = self._current_path
        if not path or not self.key_edit.isEnabled():
            return
        new_key = self.key_edit.text().strip()
        if not new_key:
            return
        container = jsonc.get_node(self.doc, path[:-1])
        old_key = path[-1]
        if new_key == old_key:
            return
        if container.get(new_key) is not None:
            QMessageBox.warning(self, "Duplicate key", f"Key {new_key!r} already exists here.")
            self._on_selection_changed()
            return
        member = container.get(old_key)
        member.key = new_key
        self.changed.emit()
        self._rebuild(select_path=path[:-1] + (new_key,))

    def _apply_value(self):
        path = self._current_path
        if not path and path != ():
            return
        node = jsonc.get_node(self.doc, path)
        if isinstance(node, (jsonc.ObjNode, jsonc.ArrNode)):
            return
        t = node.type_name()
        try:
            if t == "boolean":
                node.set_value(self.value_check.isChecked())
            elif t == "number":
                text = self.value_line.text().strip()
                node.set_value(int(text) if text.lstrip("-").isdigit() else float(text))
            elif t == "string":
                node.set_value(self.value_line.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid value", "Could not parse that value for the selected type.")
            return
        self.changed.emit()
        item = self.tree.currentItem()
        if item is not None:
            item.setText(1, _short(node.value()))

    def _on_type_changed(self, new_type):
        path = self._current_path
        if path is None:
            return
        node = jsonc.get_node(self.doc, path)
        current_type = node.type_name()
        if new_type == current_type:
            return
        has_children = isinstance(node, jsonc.ObjNode) and node.members
        has_children = has_children or (isinstance(node, jsonc.ArrNode) and node.items)
        if has_children:
            resp = QMessageBox.question(
                self, "Change type",
                "This container has children - changing its type will delete them. Continue?")
            if resp != QMessageBox.Yes:
                self.type_combo.blockSignals(True)
                self.type_combo.setCurrentText(current_type)
                self.type_combo.blockSignals(False)
                return

        if path == ():
            QMessageBox.warning(self, "Not supported", "Changing the root value's type isn't supported.")
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentText(current_type)
            self.type_combo.blockSignals(False)
            return

        container = jsonc.get_node(self.doc, path[:-1])
        key_or_index = path[-1]
        if new_type == "object":
            newval = jsonc.EMPTY_OBJECT
        elif new_type == "array":
            newval = jsonc.EMPTY_ARRAY
        elif new_type == "boolean":
            newval = False
        elif new_type == "null":
            newval = None
        elif new_type == "number":
            newval = 0
        else:
            newval = ""

        depth = node.depth
        new_node = jsonc.construct_value_node(newval, depth)
        if isinstance(container, jsonc.ObjNode):
            container.get(key_or_index).value = new_node
        else:
            container.items[key_or_index].value = new_node

        self.changed.emit()
        self._rebuild(select_path=path)

    # ---- add / delete ------------------------------------------------

    def _add_child(self):
        path = self._current_path
        if path is None:
            return
        node = jsonc.get_node(self.doc, path)
        if isinstance(node, jsonc.ObjNode):
            dlg = AddChildDialog(self, is_object=True)
            if dlg.exec() != QDialog.Accepted:
                return
            key = dlg.result_key()
            if not key:
                QMessageBox.warning(self, "Missing key", "Enter a key name.")
                return
            if node.get(key) is not None:
                QMessageBox.warning(self, "Duplicate key", f"Key {key!r} already exists.")
                return
            self.doc.add_member(node, key, dlg.result_value())
            self.changed.emit()
            self._rebuild(select_path=path + (key,))
        elif isinstance(node, jsonc.ArrNode):
            dlg = AddChildDialog(self, is_object=False)
            if dlg.exec() != QDialog.Accepted:
                return
            self.doc.add_item(node, dlg.result_value())
            self.changed.emit()
            self._rebuild(select_path=path + (len(node.items) - 1,))
        else:
            QMessageBox.information(self, "Not a container",
                                     "Select an object or array to add a child to it.")

    def _delete_selected(self):
        path = self._current_path
        if not path:
            return
        resp = QMessageBox.question(self, "Delete", f"Delete {path[-1]!r}?")
        if resp != QMessageBox.Yes:
            return
        container = jsonc.get_node(self.doc, path[:-1])
        key_or_index = path[-1]
        if isinstance(container, jsonc.ObjNode):
            self.doc.delete_member(container, key_or_index)
        else:
            self.doc.delete_item(container, key_or_index)
        self.changed.emit()
        self._rebuild(select_path=path[:-1])

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        path = item.data(0, Qt.UserRole)
        node = jsonc.get_node(self.doc, path)
        if isinstance(node, (jsonc.ObjNode, jsonc.ArrNode)):
            menu.addAction("Add child…", self._add_child)
        if path != ():
            menu.addAction("Delete", self._delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
