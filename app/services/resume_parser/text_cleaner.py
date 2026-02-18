"""
Text cleaning and normalization for resume text.

Handles unicode normalization, ligature fixing, bullet normalization,
whitespace collapsing, and boilerplate removal.
"""

import re
import unicodedata
from typing import List


# Common ligature replacements
LIGATURES = {
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb00": "ff",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

# Bullet characters to normalize
BULLET_CHARS = re.compile(r"[•●○◦▪▫►▸‣⁃∙·»→⮞➤➢☛✦✧✓✔☑⊳⊲△▶]")

# Common template boilerplate to strip
BOILERPLATE_PATTERNS = [
    re.compile(r"(?i)^\s*references?\s+available\s+(?:upon|on)\s+request\.?\s*$"),
    re.compile(r"(?i)^\s*referencias?\s+disponibles?\s+(?:a\s+solicitud|bajo\s+petici[oó]n)\.?\s*$"),
    re.compile(r"(?i)^\s*page\s+\d+\s+of\s+\d+\s*$"),
    re.compile(r"(?i)^\s*curriculum\s+vitae\s*$"),
    re.compile(r"(?i)^\s*resume\s*$"),
    re.compile(r"(?i)^\s*hoja\s+de\s+vida\s*$"),
]


class TextCleaner:
    """Cleans and normalizes raw resume text for downstream processing."""

    def clean(self, raw_text: str) -> str:
        """
        Full cleaning pipeline for resume text.

        Args:
            raw_text: Raw extracted text from document parser

        Returns:
            Cleaned, normalized text
        """
        if not raw_text:
            return ""

        text = raw_text

        # Unicode NFKD normalization (expands ligatures, compat chars),
        # then NFC recomposition (preserves accented chars like ó, é for regex matching)
        text = unicodedata.normalize("NFKD", text)
        text = unicodedata.normalize("NFC", text)

        # Fix ligatures
        for lig, replacement in LIGATURES.items():
            text = text.replace(lig, replacement)

        # Normalize bullet characters to dash
        text = BULLET_CHARS.sub("-", text)

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Collapse tabs to single space
        text = text.replace("\t", " ")

        # Collapse multiple spaces (but preserve newlines)
        text = re.sub(r" {2,}", " ", text)

        # Strip trailing whitespace from each line
        lines = text.split("\n")
        lines = [line.rstrip() for line in lines]

        # Remove boilerplate lines
        lines = self._strip_boilerplate(lines)

        # Collapse excessive blank lines (3+ → 2)
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _strip_boilerplate(self, lines: List[str]) -> List[str]:
        """Remove common resume template boilerplate lines."""
        cleaned = []
        for line in lines:
            is_boilerplate = any(p.match(line) for p in BOILERPLATE_PATTERNS)
            if not is_boilerplate:
                cleaned.append(line)
        return cleaned
