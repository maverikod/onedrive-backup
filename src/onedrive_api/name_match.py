"""File name key, wildcard pattern and stored-copy parsing of the name filter (matrix 10.19.3 and 10.19.4)."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

MAX_PATTERN = 128
MAX_STARS = 8
MIN_SUGGEST_CHARS = 2
CONTROL = re.compile("[\u0000-\u001f\u007f]")
# A stored copy of a document library collision: <stem>.dup-<h><ext>, h = 8, 12, 16 ... lowercase hex digits.
COPY = re.compile(r"^(?P<stem>.*)\.dup-(?P<h>[0-9a-f]{8,64})(?P<ext>\.[^.]*)?$", re.S)


class PatternError(ValueError):
    """The name part breaks the grammar of 10.19.3."""


@dataclass(frozen=True)
class Pattern:
    """A parsed name part.

    Attributes:
        like: SQL LIKE pattern over the name key, escape character backslash.
        empty: True when the pattern matches every name.
        wild: True when an unescaped star is present (anchored full-name pattern).
        literal: Number of characters that are not unescaped stars.
        text: The trimmed text as typed.
        prefix: LIKE pattern of the names that start with the typed text, or the empty string.
    """

    like: str
    empty: bool
    wild: bool
    literal: int
    text: str
    prefix: str


def key(text: str) -> str:
    """Return casefold(NFC(text)), the name key of 10.17.2.

    Args:
        text: A file name or a pattern.

    Returns:
        The comparison key.
    """
    return unicodedata.normalize("NFC", text).casefold()


def _like_char(char: str) -> str:
    """Escape one literal character for a LIKE pattern.

    Args:
        char: One character.

    Returns:
        The character, prefixed by a backslash when LIKE gives it a meaning.
    """
    return "\\" + char if char in "\\%_" else char


def parse_pattern(value: object) -> Pattern:
    """Parse a name part: trim, check the grammar and build the LIKE pattern.

    Args:
        value: The name part as typed (a star is any sequence, backslash-star a literal star).

    Returns:
        The parsed pattern.

    Raises:
        PatternError: Not a string, longer than 128 characters, a control character or more than 8 stars.
    """
    if not isinstance(value, str):
        raise PatternError("name part must be a string")
    text = value.strip()
    if len(text) > MAX_PATTERN or CONTROL.search(text):
        raise PatternError("name part is longer than %d characters or holds a control character" % MAX_PATTERN)
    source, parts, stars, literal, plain, index = key(text), [], 0, 0, [], 0
    while index < len(source):
        char = source[index]
        if char == "\\" and source[index + 1:index + 2] in ("*", "\\"):
            index += 1
            char = source[index]
        elif char == "*":
            stars += 1
            parts.append("%")
            plain.append("%")
            index += 1
            continue
        parts.append(_like_char(char))
        plain.append(_like_char(char))
        literal += 1
        index += 1
    if stars > MAX_STARS:
        raise PatternError("name part has more than %d stars" % MAX_STARS)
    body = "".join(parts)
    if stars == 0:
        return Pattern("%" + body + "%", literal == 0, False, literal, text, body + "%" if body else "")
    return Pattern(body, literal == 0, True, literal, text, "")


def split_stored(stored: str) -> tuple[str, str]:
    """Split a stored name into the shown name and the copy digits.

    Args:
        stored: The base name in the mirror.

    Returns:
        The shown name (the original name without the dup fragment) and the hex digits, empty for a primary.
    """
    found = COPY.match(stored)
    if found is None:
        return stored, ""
    return found.group("stem") + (found.group("ext") or ""), found.group("h")
