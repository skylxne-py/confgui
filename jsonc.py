"""
Comment-preserving JSONC (JSON-with-comments) parser and editor model.

Waybar's config file is JSONC: standard JSON plus `//` and `/* */` comments
and (leniently) trailing commas. Round-tripping through plain json.load/dump
would silently delete every comment, so this module parses into a small
mutable tree that remembers the exact source text ("trivia": whitespace and
comments) around every token. Editing a value only touches that value's own
node; everything else is re-emitted byte-for-byte.

Trivia ownership rule (this is what keeps insert/delete simple and correct):
a container's `open_trivia` holds everything between its opening bracket and
its first child. Each member/item holds `pre_comma` (trivia between its value
and its own comma, empty in virtually all real files), and `trail` (trivia
AFTER its comma, up to the next sibling's key/value or the closing bracket).
For the last child, `comma` is False and `pre_comma` plays the role that
`trail` would otherwise play (the trivia leading to the closing bracket).

Supported edits: change a scalar's value/type, rename an object key,
add/delete an object member, add/delete an array item.
"""
import re
import json


class JsoncError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<line_comment>//[^\n]*)
  | (?P<string>"(?:\\.|[^"\\])*")
  | (?P<number>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<true>\btrue\b)
  | (?P<false>\bfalse\b)
  | (?P<null>\bnull\b)
  | (?P<lbrace>\{)
  | (?P<rbrace>\})
  | (?P<lbracket>\[)
  | (?P<rbracket>\])
  | (?P<colon>:)
  | (?P<comma>,)
    """,
    re.DOTALL | re.VERBOSE,
)

TRIVIA_KINDS = {"ws", "block_comment", "line_comment"}


def tokenize(text):
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            snippet = text[pos:pos + 30].splitlines()[0]
            raise JsoncError(f"Unexpected character at offset {pos}: {snippet!r}")
        tokens.append((m.lastgroup, m.group()))
        pos = m.end()
    return tokens


# ---------------------------------------------------------------------------
# Tree nodes
# ---------------------------------------------------------------------------

class Scalar:
    __slots__ = ("kind", "raw", "depth")

    def __init__(self, kind, raw, depth=0):
        self.kind = kind  # 'string' | 'number' | 'true' | 'false' | 'null'
        self.raw = raw
        self.depth = depth

    def value(self):
        if self.kind == "string":
            return json.loads(self.raw)
        if self.kind == "number":
            return int(self.raw) if re.fullmatch(r"-?\d+", self.raw) else float(self.raw)
        if self.kind == "true":
            return True
        if self.kind == "false":
            return False
        return None

    def set_value(self, pyval):
        self.kind, self.raw = _kind_and_raw_for(pyval)

    def serialize(self):
        return self.raw

    def type_name(self):
        return {"true": "boolean", "false": "boolean"}.get(self.kind, self.kind)


class Member:
    __slots__ = ("key_raw", "mid1", "mid2", "value", "pre_comma", "comma", "trail")

    def __init__(self, key_raw, mid1, mid2, value, pre_comma, comma, trail):
        self.key_raw = key_raw
        self.mid1 = mid1
        self.mid2 = mid2
        self.value = value
        self.pre_comma = pre_comma
        self.comma = comma
        self.trail = trail

    @property
    def key(self):
        return json.loads(self.key_raw)

    @key.setter
    def key(self, newkey):
        self.key_raw = json.dumps(newkey)

    def serialize(self):
        comma = "," if self.comma else ""
        return f"{self.key_raw}{self.mid1}:{self.mid2}{self.value.serialize()}{self.pre_comma}{comma}{self.trail}"


class ObjNode:
    __slots__ = ("open_trivia", "members", "depth")
    kind = "object"

    def __init__(self, open_trivia, members, depth=0):
        self.open_trivia = open_trivia
        self.members = members
        self.depth = depth

    def serialize(self):
        return "{" + self.open_trivia + "".join(m.serialize() for m in self.members) + "}"

    def type_name(self):
        return "object"

    def keys(self):
        return [m.key for m in self.members]

    def get(self, key):
        for m in self.members:
            if m.key == key:
                return m
        return None

    def index_of(self, key):
        for i, m in enumerate(self.members):
            if m.key == key:
                return i
        return -1


class Item:
    __slots__ = ("value", "pre_comma", "comma", "trail")

    def __init__(self, value, pre_comma, comma, trail):
        self.value = value
        self.pre_comma = pre_comma
        self.comma = comma
        self.trail = trail

    def serialize(self):
        comma = "," if self.comma else ""
        return f"{self.value.serialize()}{self.pre_comma}{comma}{self.trail}"


class ArrNode:
    __slots__ = ("open_trivia", "items", "depth")
    kind = "array"

    def __init__(self, open_trivia, items, depth=0):
        self.open_trivia = open_trivia
        self.items = items
        self.depth = depth

    def serialize(self):
        return "[" + self.open_trivia + "".join(it.serialize() for it in self.items) + "]"

    def type_name(self):
        return "array"


def _kind_and_raw_for(pyval):
    if isinstance(pyval, bool):
        return ("true" if pyval else "false"), ("true" if pyval else "false")
    if pyval is None:
        return "null", "null"
    if isinstance(pyval, (int, float)):
        return "number", json.dumps(pyval)
    if isinstance(pyval, str):
        return "string", json.dumps(pyval)
    raise JsoncError(f"Unsupported scalar python value: {pyval!r}")


EMPTY_OBJECT = object()
EMPTY_ARRAY = object()


def construct_value_node(pyval, depth):
    """Build a brand-new node (used for values inserted via the GUI)."""
    if pyval is EMPTY_OBJECT:
        return ObjNode("", [], depth)
    if pyval is EMPTY_ARRAY:
        return ArrNode("", [], depth)
    kind, raw = _kind_and_raw_for(pyval)
    return Scalar(kind, raw, depth)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.n = len(tokens)

    def _peek(self):
        return self.tokens[self.i] if self.i < self.n else (None, "")

    def collect_trivia(self):
        buf = []
        while self.i < self.n and self.tokens[self.i][0] in TRIVIA_KINDS:
            buf.append(self.tokens[self.i][1])
            self.i += 1
        return "".join(buf)

    def expect(self, kind):
        actual, text = self._peek()
        if actual != kind:
            raise JsoncError(f"Expected {kind!r} but found {actual!r} ({text!r}) at token {self.i}")
        self.i += 1
        return text

    def parse_value(self, depth):
        kind, text = self._peek()
        if kind == "lbrace":
            return self.parse_object(depth)
        if kind == "lbracket":
            return self.parse_array(depth)
        if kind in ("string", "number", "true", "false", "null"):
            self.i += 1
            return Scalar(kind, text, depth)
        raise JsoncError(f"Expected a value but found {kind!r} ({text!r}) at token {self.i}")

    def parse_object(self, depth):
        self.expect("lbrace")
        open_trivia = self.collect_trivia()
        members = []
        if self._peek()[0] == "rbrace":
            self.expect("rbrace")
            return ObjNode(open_trivia, members, depth)
        while True:
            key_raw = self.expect("string")
            mid1 = self.collect_trivia()
            self.expect("colon")
            mid2 = self.collect_trivia()
            value = self.parse_value(depth + 1)
            pre_comma = self.collect_trivia()
            comma = False
            trail = ""
            if self._peek()[0] == "comma":
                self.expect("comma")
                comma = True
                trail = self.collect_trivia()
            members.append(Member(key_raw, mid1, mid2, value, pre_comma, comma, trail))
            if self._peek()[0] == "rbrace":
                self.expect("rbrace")
                return ObjNode(open_trivia, members, depth)

    def parse_array(self, depth):
        self.expect("lbracket")
        open_trivia = self.collect_trivia()
        items = []
        if self._peek()[0] == "rbracket":
            self.expect("rbracket")
            return ArrNode(open_trivia, items, depth)
        while True:
            value = self.parse_value(depth + 1)
            pre_comma = self.collect_trivia()
            comma = False
            trail = ""
            if self._peek()[0] == "comma":
                self.expect("comma")
                comma = True
                trail = self.collect_trivia()
            items.append(Item(value, pre_comma, comma, trail))
            if self._peek()[0] == "rbracket":
                self.expect("rbracket")
                return ArrNode(open_trivia, items, depth)


class JsoncDocument:
    def __init__(self, lead_trivia, root, trail_trivia):
        self.lead_trivia = lead_trivia
        self.root = root
        self.trail_trivia = trail_trivia

    def serialize(self):
        return self.lead_trivia + self.root.serialize() + self.trail_trivia

    # ---- mutation helpers -------------------------------------------------

    def _indent_template(self, container):
        """A '\\n' + spaces string used as the leading trivia for a new child."""
        trivia = container.open_trivia
        if not trivia and (container.members if isinstance(container, ObjNode) else container.items):
            first = container.members[0] if isinstance(container, ObjNode) else container.items[0]
            trivia = first.trail if first.comma else first.pre_comma
        if "\n" in trivia:
            return "\n" + trivia.rsplit("\n", 1)[1]
        return "\n" + "  " * (container.depth + 1)

    def _close_indent(self, container):
        return "\n" + "  " * container.depth

    def _insert_common(self, container, children, index, new_child):
        indent = self._indent_template(container)
        if not children:
            container.open_trivia = indent
            new_child.comma = False
            new_child.pre_comma = self._close_indent(container)
            children.append(new_child)
            return
        if index is None or index >= len(children):
            prev = children[-1]
            if prev.comma:
                carry = prev.trail
                prev.trail = indent
            else:
                carry = prev.pre_comma
                prev.pre_comma = ""
                prev.comma = True
                prev.trail = indent
            new_child.pre_comma = carry if carry else self._close_indent(container)
            new_child.comma = False
            new_child.trail = ""
            children.append(new_child)
        else:
            new_child.pre_comma = ""
            new_child.comma = True
            new_child.trail = indent
            children.insert(index, new_child)

    def _delete_common(self, container, children, index):
        children.pop(index)
        if not children:
            container.open_trivia = ""
            return
        if index == len(children):  # we removed the last element
            new_last = children[-1]
            if new_last.comma:
                new_last.pre_comma = new_last.trail
                new_last.trail = ""
                new_last.comma = False

    def add_member(self, obj, key, pyval, index=None):
        if obj.get(key) is not None:
            raise JsoncError(f"Key {key!r} already exists")
        value_node = construct_value_node(pyval, obj.depth + 1)
        new_member = Member(json.dumps(key), "", " ", value_node, "", False, "")
        self._insert_common(obj, obj.members, index, new_member)
        return new_member

    def delete_member(self, obj, key):
        idx = obj.index_of(key)
        if idx < 0:
            raise JsoncError(f"Key {key!r} not found")
        self._delete_common(obj, obj.members, idx)

    def add_item(self, arr, pyval, index=None):
        value_node = construct_value_node(pyval, arr.depth + 1)
        new_item = Item(value_node, "", False, "")
        self._insert_common(arr, arr.items, index, new_item)
        return new_item

    def delete_item(self, arr, index):
        self._delete_common(arr, arr.items, index)


def parse(text):
    tokens = tokenize(text)
    p = _Parser(tokens)
    lead = p.collect_trivia()
    root = p.parse_value(0)
    trail = p.collect_trivia()
    if p.i != p.n:
        kind, tok = p._peek()
        raise JsoncError(f"Unexpected trailing content: {kind!r} {tok!r}")
    return JsoncDocument(lead, root, trail)


# ---------------------------------------------------------------------------
# Path-based navigation, used by the GUI tree widget
# ---------------------------------------------------------------------------

def get_node(doc, path):
    node = doc.root
    for step in path:
        if isinstance(node, ObjNode):
            m = node.get(step)
            if m is None:
                raise KeyError(step)
            node = m.value
        elif isinstance(node, ArrNode):
            node = node.items[step].value
        else:
            raise TypeError("Cannot descend into a scalar")
    return node


def get_container_and_key(doc, path):
    """Return (container_node, key_or_index) for the parent of `path`."""
    parent = get_node(doc, path[:-1])
    return parent, path[-1]
