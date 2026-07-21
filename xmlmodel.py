"""
Thin XML helpers built on stdlib xml.etree.ElementTree.

Unlike jsonc.py this does not do full source-byte round-tripping: on save,
xml.etree.ElementTree.indent() re-normalizes whitespace-only text/tail so the
file comes out consistently indented. Comments ARE preserved (parsed as real
Comment nodes via TreeBuilder(insert_comments=True)) and any actual element
text content is left untouched by indent() - only pure-whitespace formatting
gets reflowed. That trade-off (keep content + comments, accept re-indentation)
matches how these WM config files are normally hand-edited anyway.

Two things ElementTree gets wrong by default, worked around here:
- It forgets the source's namespace prefixes and invents ns0/ns1/... on
  serialization. We capture the real prefix->uri declarations while parsing
  (via a start_ns hook) and re-register them so tostring() reuses them - this
  matters for real rc.xml files, which declare a default `xmlns=`.
- A comment sitting before the root element (e.g. a "do not edit" header,
  common in openbox/labwc rc.xml) isn't part of the element tree at all and
  gets silently dropped. We snip that block out as raw text before parsing
  and re-prepend it on serialize. A comment placed *after* the root element
  is rare enough that we don't attempt to preserve it.
"""
import re
import xml.etree.ElementTree as ET

_XML_DECL_RE = re.compile(r"\A\s*(<\?xml[^>]*\?>)")
_LEADING_COMMENT_RE = re.compile(r"\s*<!--.*?-->", re.DOTALL)


class _NSCollectingBuilder(ET.TreeBuilder):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.ns_map = []

    def start_ns(self, prefix, uri):
        self.ns_map.append((prefix, uri))


class XmlDocument:
    def __init__(self, root, xml_decl, pre_root_trivia):
        self.root = root
        self.xml_decl = xml_decl  # original '<?xml ...?>' line, or None
        self.pre_root_trivia = pre_root_trivia  # raw text (comments) before <root>

    def serialize(self):
        tree_copy = ET.ElementTree(self.root)
        ET.indent(tree_copy, space="  ")
        body = ET.tostring(self.root, encoding="unicode")
        out = ""
        if self.xml_decl:
            out += self.xml_decl + "\n"
        if self.pre_root_trivia:
            out += self.pre_root_trivia.strip() + "\n"
        out += body + "\n"
        return out


def _split_pre_root(text):
    """Peel off any whitespace/comments that precede the root element."""
    i = 0
    while True:
        m = _LEADING_COMMENT_RE.match(text, i)
        if not m:
            break
        i = m.end()
    return text[:i], text[i:]


def parse(text):
    m = _XML_DECL_RE.match(text)
    xml_decl = None
    if m:
        xml_decl = m.group(1)
        text = text[m.end():]
    pre_root_trivia, text = _split_pre_root(text)

    target = _NSCollectingBuilder(insert_comments=True, insert_pis=True)
    parser = ET.XMLParser(target=target)
    parser.feed(text)
    root = parser.close()
    for prefix, uri in target.ns_map:
        ET.register_namespace(prefix, uri)
    return XmlDocument(root, xml_decl, pre_root_trivia)


def is_comment(el):
    return el.tag is ET.Comment


def is_pi(el):
    return el.tag is ET.ProcessingInstruction


def tag_label(el):
    if is_comment(el):
        text = (el.text or "").strip()
        return f"<!-- {text[:60]} -->" if text else "<!-- -->"
    if is_pi(el):
        return f"<?{el.text}?>"
    return el.tag


def new_element(tag):
    return ET.Element(tag)


def new_comment(text=" comment "):
    c = ET.Comment(text)
    return c
