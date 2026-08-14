from __future__ import annotations

from typing import Any, Tuple


def normalize_warning_messages(value: Any) -> Tuple[str, ...]:
    """Normalize warning/limitation payloads for safe UI iteration."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (tuple, list)):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            for message in normalize_warning_messages(item):
                if message not in seen:
                    seen.add(message)
                    normalized.append(message)
        return tuple(normalized)
    return ()


def merge_warning_messages(*sources: Any) -> Tuple[str, ...]:
    """Merge multiple warning sources without character-level expansion."""
    normalized: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for message in normalize_warning_messages(source):
            if message not in seen:
                seen.add(message)
                normalized.append(message)
    return tuple(normalized)
