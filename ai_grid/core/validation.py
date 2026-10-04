# ai_grid/core/validation.py
"""
Centralized Input Validation and Sanitization Module for Automata Grid.
Enforces strict boundaries, character sets, and RFC 1459/2812 compliance.
"""

from __future__ import annotations
import re
from typing import Any, Optional

# Pre-compiled regex patterns for optimal performance
# RFC 1459/2812 standard IRC nick characters: alphanumeric plus []\_{}^-|
RE_NICKNAME = re.compile(r"^[a-zA-Z0-9\[\]\\_{}^|\-]+$")

# Grid node names: alphanumeric plus underscore, max 11 characters
RE_NODE_NAME = re.compile(r"^[a-zA-Z0-9_]+$")

# Item names: alphanumeric, underscore, hyphen, space (1-50 characters)
RE_ITEM_NAME = re.compile(r"^[a-zA-Z0-9_\- ]+$")

# UUID / Auth token: alphanumeric and hyphens
RE_AUTH_TOKEN = re.compile(r"^[a-zA-Z0-9\-]+$")

# Canonical direction mappings
DIRECTION_MAP = {
    "north": "north", "n": "north",
    "south": "south", "s": "south",
    "east": "east",   "e": "east",
    "west": "west",   "w": "west",
    "up": "up",       "u": "up",
    "down": "down",   "d": "down",
}


def validate_nickname(nick: Optional[str]) -> bool:
    """
    Validates an IRC nickname.
    Must be alphanumeric + standard IRC chars `[]\\_{}^-|`, length 1-30.
    """
    if not isinstance(nick, str) or not nick:
        return False
    if not (1 <= len(nick) <= 30):
        return False
    return bool(RE_NICKNAME.match(nick))


def validate_node_name(name: Optional[str]) -> bool:
    """
    Validates a grid node name.
    Must be alphanumeric + `_`, length 1-11.
    """
    if not isinstance(name, str) or not name:
        return False
    if not (1 <= len(name) <= 11):
        return False
    return bool(RE_NODE_NAME.match(name))


def validate_direction(dir_str: Optional[str]) -> Optional[str]:
    """
    Validates a navigational direction.
    Accepts full or abbreviated directions (case-insensitive).
    Returns normalized canonical direction: 'north', 'south', 'east', 'west', 'up', 'down'.
    Returns None if invalid.
    """
    if not isinstance(dir_str, str) or not dir_str:
        return None
    return DIRECTION_MAP.get(dir_str.strip().lower())


def validate_item_name(item: Optional[str]) -> bool:
    """
    Validates an item name format.
    Must be alphanumeric + `_- `, non-empty, 1-50 characters.
    """
    if not isinstance(item, str) or not item.strip():
        return False
    s = item.strip()
    if not (1 <= len(s) <= 50):
        return False
    return bool(RE_ITEM_NAME.match(s))


def validate_quantity(
    qty: Any,
    min_val: int = 1,
    max_val: int = 1_000_000_000
) -> Optional[int]:
    """
    Validates and bounds an integer quantity (credits, power, bets, auction amounts).
    Handles strings, ints, floats (with integer value).
    Rejects booleans, negatives, zero (if min_val >= 1), non-integers, and overflows.
    Returns integer if valid, None otherwise.
    """
    if qty is None or isinstance(qty, bool):
        return None
    try:
        if isinstance(qty, str):
            s = qty.strip()
            # Prevent int parsing DoS on huge digit strings
            if len(s) > 15:
                return None
            val = int(s)
        elif isinstance(qty, (int, float)):
            if isinstance(qty, float) and not qty.is_integer():
                return None
            val = int(qty)
        else:
            return None
    except (ValueError, TypeError, OverflowError):
        return None

    if min_val <= val <= max_val:
        return val
    return None


def validate_token(token: Optional[str]) -> bool:
    """
    Validates player authentication tokens (UUID strings).
    Must be alphanumeric + hyphens, length 8-64.
    """
    if not isinstance(token, str) or not token:
        return False
    if not (8 <= len(token) <= 64):
        return False
    return bool(RE_AUTH_TOKEN.match(token))


def sanitize_irc_outbound(text: Optional[str], max_bytes: int = 510) -> str:
    """
    Sanitizes outbound IRC text for RFC 1459/2812 compliance.
    - Strips all `\\r` and `\\n` to prevent CRLF injection.
    - Truncates to max_bytes in UTF-8 without corrupting multi-byte code points.
    - Wire payload with `\\r\\n` will never exceed 512 bytes (max_bytes + 2).
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    cleaned = text.replace("\r", "").replace("\n", "")
    encoded = cleaned.encode("utf-8")
    if len(encoded) <= max_bytes:
        return cleaned
    # Slice bytes to max_bytes and decode with 'ignore' to drop partial code points
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
