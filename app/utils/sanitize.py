"""
Sanitization utilities for user-generated text.

All functions accept None and return None so they can be used safely as
Pydantic field validators on optional fields without special-casing.
"""

from typing import Optional

import bleach


# Tags and attributes allowed in rich-text fields (job/company descriptions).
_RICH_TEXT_TAGS: list[str] = ["p", "br", "strong", "em", "ul", "ol", "li", "a"]
_RICH_TEXT_ATTRS: dict[str, list[str]] = {"a": ["href", "title"]}


def sanitize_plain_text(value: Optional[str]) -> Optional[str]:
    """Strip ALL HTML tags from a plain-text field.

    Suitable for titles, names, headlines, short bios, and any field that
    should never contain markup.  Uses ``strip=True`` so tags are removed
    rather than entity-escaped.

    Args:
        value: Raw string from user input, or None.

    Returns:
        Sanitized string with all HTML stripped, or None if input is None.
    """
    if value is None:
        return None
    return bleach.clean(value, tags=[], attributes={}, strip=True)


def sanitize_rich_text(value: Optional[str]) -> Optional[str]:
    """Allow a safe whitelist of HTML tags in rich-text fields.

    Suitable for job descriptions, company descriptions, and other long-form
    content where basic formatting is acceptable.

    Allowed tags: ``p``, ``br``, ``strong``, ``em``, ``ul``, ``ol``,
    ``li``, ``a``.
    Allowed attributes: ``href`` and ``title`` on ``<a>`` only.

    Args:
        value: Raw string from user input, or None.

    Returns:
        Sanitized string with disallowed tags stripped, or None if input
        is None.
    """
    if value is None:
        return None
    return bleach.clean(
        value,
        tags=_RICH_TEXT_TAGS,
        attributes=_RICH_TEXT_ATTRS,
        strip=True,
    )
