# confgui

A small PySide6 GUI for editing Linux desktop configs - Waybar's
`config.jsonc`, Openbox/labwc-style `rc.xml` / `menu.xml`, and more - through
form fields instead of hand-editing JSON/XML, with a one-click raw code
editor for anything the structured view can't handle.

## Install

Needs Python 3 and PySide6.

```sh
# Arch:
sudo pacman -S pyside6

# Other distros / no system package:
pip install --user PySide6
```

## Run

```sh
./main.py                    # opens empty, use the sidebar to pick a file
./main.py ~/.config/waybar/config.jsonc   # opens directly into that file
```

## What it does

- **Sidebar shortcuts** - on launch it scans for common configs (Waybar
  `config.jsonc`/`style.css`, labwc/openbox `rc.xml`/`menu.xml`, Sway,
  Hyprland, Mako, GTK settings...) and lists whichever ones actually exist on
  disk. Double-click to load. Edit `registry.py` to add more.
- **Manual loader** - type a path or click "Browse..." for a normal file
  picker.
- **Structured editing** - JSON/JSONC files show as a tree (Key / Value /
  Type columns); select a node to rename its key, change its type, or edit
  its value in the panel below. Right-click (or the "Add child.../Delete"
  buttons) to add or remove object keys / array items. XML files work the
  same way, with a table for attributes and a box for text content.
- **Comments are preserved.** Waybar's `.jsonc` comments (`//` and `/* */`)
  round-trip through edits untouched wherever you didn't change something.
  XML comments are preserved too, though saving an XML file does reflow
  whitespace-only indentation (actual content/comments are left alone).
- **Raw code editor** - the "Switch to code editor" toolbar button drops into
  a plain syntax-highlighted text editor over the same file, for anything the
  form view doesn't model. Switching back to the form view re-parses your
  raw edits; if they don't parse, you stay in the raw view until they do (or
  you can save the raw text anyway with a confirmation).
- Files with no structured editor (`style.css`, `sway/config`,
  `hyprland.conf`, ...) open straight into the raw editor.

## Files

- `jsonc.py` - comment-preserving JSONC parser/editor model (hand-written,
  no dependency; tested against a real Waybar config for byte-identical
  round-tripping).
- `xmlmodel.py` - thin ElementTree wrapper with namespace-prefix and
  leading-comment preservation.
- `registry.py` - the list of auto-detected config shortcuts.
- `json_tree_widget.py` / `xml_tree_widget.py` - the structured tree editors.
- `raw_editor.py` - the lightweight code-editor fallback.
- `main_window.py` / `main.py` - the application shell.

## Known limitations

- XML editing re-indents the whole file on save (2-space indent); element
  content and comments are untouched, but exact original whitespace/line
  wrapping isn't preserved byte-for-byte the way JSONC edits are.
- A comment placed *after* the root XML element (rare) isn't preserved.
