"""
Known-config registry used to populate the "detected configs" shortcut list.

Each entry lists one or more candidate paths (tried in order, first existing
one wins) plus a format hint that tells the main window which editor to open:
  'jsonc' -> structured JSON tree editor, comments preserved
  'json'  -> structured JSON tree editor, plain json module
  'xml'   -> structured XML tree editor
  'text'  -> raw code editor only (format the structured editors don't model)

To add more shortcuts, just append to REGISTRY below.
"""
import os

REGISTRY = [
    {
        "label": "Waybar config",
        "candidates": ["~/.config/waybar/config.jsonc", "~/.config/waybar/config"],
        "format": "jsonc",
    },
    {
        "label": "Waybar style.css",
        "candidates": ["~/.config/waybar/style.css"],
        "format": "text",
    },
    {
        "label": "labwc rc.xml",
        "candidates": ["~/.config/labwc/rc.xml"],
        "format": "xml",
    },
    {
        "label": "labwc menu.xml",
        "candidates": ["~/.config/labwc/menu.xml"],
        "format": "xml",
    },
    {
        "label": "labwc autostart",
        "candidates": ["~/.config/labwc/autostart"],
        "format": "text",
    },
    {
        "label": "labwc environment",
        "candidates": ["~/.config/labwc/environment"],
        "format": "text",
    },
    {
        "label": "Openbox rc.xml",
        "candidates": ["~/.config/openbox/rc.xml"],
        "format": "xml",
    },
    {
        "label": "Openbox menu.xml",
        "candidates": ["~/.config/openbox/menu.xml"],
        "format": "xml",
    },
    {
        "label": "Sway config",
        "candidates": ["~/.config/sway/config"],
        "format": "text",
    },
    {
        "label": "Hyprland config",
        "candidates": ["~/.config/hypr/hyprland.conf"],
        "format": "text",
    },
    {
        "label": "Mako config",
        "candidates": ["~/.config/mako/config"],
        "format": "text",
    },
    {
        "label": "GTK 3 settings.ini",
        "candidates": ["~/.config/gtk-3.0/settings.ini"],
        "format": "text",
    },
    {
        "label": "GTK 4 settings.ini",
        "candidates": ["~/.config/gtk-4.0/settings.ini"],
        "format": "text",
    },
]


def discover():
    """Return REGISTRY entries whose file actually exists, each augmented
    with a resolved absolute 'path'."""
    found = []
    for entry in REGISTRY:
        for candidate in entry["candidates"]:
            resolved = os.path.expanduser(candidate)
            if os.path.isfile(resolved):
                found.append({**entry, "path": resolved})
                break
    return found


def guess_format(path):
    """Best-effort format guess for a manually-opened file, by extension."""
    lower = path.lower()
    if lower.endswith((".jsonc",)):
        return "jsonc"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".xml"):
        return "xml"
    if os.path.basename(lower) in ("config",):
        # Ambiguous filename (waybar uses this) - sniff content.
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(512).lstrip()
        except OSError:
            return "text"
        if head.startswith("{") or head.startswith("["):
            return "jsonc"
        if head.startswith("<"):
            return "xml"
    return "text"
