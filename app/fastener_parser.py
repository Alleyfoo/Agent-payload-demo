from __future__ import annotations

import re
from typing import Dict, List, Optional


def _extract_standard(text: str) -> Optional[str]:
    match = re.search(r"(DIN\s*\d+[A-Z\-]*|DIN\d+[A-Z\-]*|ISO\s*\d+|ISO\d+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).strip().upper()
    raw = raw.replace("ISO", "ISO ").replace("DIN", "DIN ")
    raw = " ".join(raw.split())
    return raw


def _extract_size_and_length(text: str) -> tuple[Optional[str], Optional[int]]:
    match = re.search(r"M\s*(\d+)(?:[xX](\d+))?", text, flags=re.IGNORECASE)
    if not match:
        return None, None
    size = f"M{match.group(1)}"
    length = None
    if match.group(2):
        try:
            length = int(match.group(2))
        except ValueError:
            length = None
    return size, length


def _extract_material(text: str) -> Optional[str]:
    if re.search(r"\bA2\b", text, flags=re.IGNORECASE):
        return "stainless A2"
    if re.search(r"\bA4\b", text, flags=re.IGNORECASE):
        return "stainless A4"
    if re.search(r"\bSS\b", text, flags=re.IGNORECASE) or re.search(r"stainless", text, flags=re.IGNORECASE):
        return "stainless"
    return None


def _extract_coating(text: str) -> Optional[str]:
    if re.search(r"\b(ZP|ZNPL|ZN|ZINC)\b", text, flags=re.IGNORECASE) or "zinc plated" in text.lower():
        return "zinc plated"
    return None


def canonicalize(lines: List[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for line in lines:
        text = line.strip()
        standard = _extract_standard(text)
        size, length = _extract_size_and_length(text)
        material = _extract_material(text)
        coating = _extract_coating(text)
        rows.append(
            {
                "standard": standard,
                "size": size,
                "length": length,
                "material": material,
                "coating": coating,
            }
        )
    return rows


__all__ = ["canonicalize"]
