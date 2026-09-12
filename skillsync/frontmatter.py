"""Minimal YAML frontmatter parser for SKILL.md files.

Deliberately dependency-free (no PyYAML). It supports the subset that skill
frontmatter actually uses in the wild:

* ``key: value`` scalars (quoted or bare)
* block scalars ``key: >`` / ``key: |`` (folded and literal)
* inline lists ``key: [a, b]``
* nested block lists ``key:\\n  - item``
* nested mappings via indentation (one or more levels)
* ``#`` comments and blank lines

This is not a general YAML implementation. It is tuned for the frontmatter
conventions used by Codex / Claude / WorkBuddy skills and fails soft: anything
it cannot parse is kept as a raw string rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


@dataclass
class Document:
    """A parsed SKILL.md: frontmatter data plus the raw markdown body."""

    data: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    raw_frontmatter: str = ""
    parse_warnings: list[str] = field(default_factory=list)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return ``(frontmatter_or_None, body)`` for raw file text."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end():]


def _strip_comment(line: str) -> str:
    """Remove a trailing ``# comment`` that is not inside quotes."""
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _coerce_scalar(token: str) -> Any:
    token = token.strip()
    if token == "" or token in ("~", "null", "Null", "NULL"):
        return None
    if token in ("true", "True", "TRUE", "yes", "Yes", "on", "On"):
        return True
    if token in ("false", "False", "FALSE", "no", "No", "off", "Off"):
        return False
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(part) for part in _split_flow(inner)]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _split_flow(inner: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for ch in inner:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def parse_frontmatter(text: str) -> Document:
    """Parse raw SKILL.md text into a :class:`Document`."""
    raw, body = split_frontmatter(text)
    if raw is None:
        return Document(body=body, parse_warnings=["no frontmatter block found"])

    doc = Document(body=body, raw_frontmatter=raw)
    # Stack entries: (indent, container). Container is the dict or list we add to.
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any, str | None]] = [(-1, root, None)]
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        stripped = _strip_comment(raw_line)
        if not stripped.strip():
            i += 1
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))

        # Block scalar: key: > or key: |
        block_match = re.match(r"^(?P<key>[A-Za-z0-9_.\-]+):\s*(?P<style>[>|][-+]?)\s*$", stripped)
        if block_match:
            key = block_match.group("key")
            style = block_match.group("style")[0]
            collected: list[str] = []
            block_indent: int | None = None
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "":
                    collected.append("")
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_indent <= indent:
                    break
                if block_indent is None:
                    block_indent = nxt_indent
                collected.append(nxt[block_indent:] if len(nxt) >= block_indent else nxt.strip())
                j += 1
            while collected and collected[-1] == "":
                collected.pop()
            value = "\n".join(collected) if style == "|" else " ".join(
                ln.strip() for ln in collected if ln.strip()
            )
            _assign(stack, indent, key, value)
            i = j
            continue

        # List item at this indent level
        if stripped.lstrip().startswith("- "):
            item_text = stripped.lstrip()[2:].strip()
            _append_list_item(stack, indent, _coerce_scalar(item_text))
            i += 1
            continue

        kv = re.match(r"^(?P<key>[A-Za-z0-9_.\-]+):\s*(?P<value>.*)$", stripped)
        if kv:
            key = kv.group("key")
            value_text = kv.group("value").strip()
            if value_text == "":
                # Could introduce a nested mapping or a block list — peek ahead.
                container = _open_container(stack, indent, key)
                if container is not None:
                    i += 1
                    continue
                _assign(stack, indent, key, None)
                i += 1
                continue
            _assign(stack, indent, key, _coerce_scalar(value_text))
            i += 1
            continue

        doc.parse_warnings.append(f"unparsed line {i + 1}: {stripped!r}")
        i += 1

    doc.data = root
    return doc


def _pop_to(stack: list[tuple[int, Any, str | None]], indent: int) -> list[tuple[int, Any, str | None]]:
    while len(stack) > 1 and stack[-1][0] >= indent:
        stack.pop()
    return stack


def _assign(stack: list[tuple[int, Any, str | None]], indent: int, key: str, value: Any) -> None:
    _pop_to(stack, indent)
    container = stack[-1][1]
    if isinstance(container, dict):
        container[key] = value
    # If the current container is a list, a stray key is ignored.


def _open_container(stack: list[tuple[int, Any, str | None]], indent: int, key: str) -> Any:
    """Register ``key`` as a container-to-be-filled by following indented lines.

    Returns the new container, or ``None`` if we cannot decide yet (in which
    case the caller treats the key as an empty scalar; later list items will
    convert it).
    """
    _pop_to(stack, indent)
    parent = stack[-1][1]
    if not isinstance(parent, dict):
        return None
    placeholder: dict[str, Any] = {}
    parent[key] = placeholder
    stack.append((indent, placeholder, key))
    return placeholder


def _append_list_item(stack: list[tuple[int, Any, str | None]], indent: int, value: Any) -> None:
    _pop_to(stack, indent)
    top_indent, container, key = stack[-1]
    parent_container = stack[-2][1] if len(stack) >= 2 else None
    if isinstance(container, dict) and not container and key and isinstance(parent_container, dict):
        # The placeholder dict we opened is actually a block list.
        new_list: list[Any] = [value]
        parent_container[key] = new_list
        stack[-1] = (top_indent, new_list, key)
        return
    if isinstance(container, list):
        container.append(value)
        return
    if isinstance(container, dict) and key is None:
        return
    # Root-level list items with no owning key are unusual; ignore.


def parse_file(path) -> Document:
    """Read ``path`` and parse its frontmatter."""
    import pathlib

    p = pathlib.Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = p.read_text(encoding="utf-8", errors="replace")
    return parse_frontmatter(text)
