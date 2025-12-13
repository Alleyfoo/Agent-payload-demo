import pytest

from app.fastener_parser import canonicalize


def test_set_a_exact_eight_lines():
    lines = [
        "DIN931 M6x30 8.8 ZP",
        "DIN 125-A M8 A2",
        "ISO 4762 M5x16 Zn",
        "DIN933 M10x50 A4",
        "DIN 7985 M4x12 ZP",
        "DIN 603 M8x40 4.6",
        "DIN934 M6 Zn",
        "DIN125-A M10 A2",
    ]
    expected = [
        {"standard": "DIN 931", "size": "M6", "length": 30, "material": None, "coating": "zinc plated"},
        {"standard": "DIN 125-A", "size": "M8", "length": None, "material": "stainless A2", "coating": None},
        {"standard": "ISO 4762", "size": "M5", "length": 16, "material": None, "coating": "zinc plated"},
        {"standard": "DIN 933", "size": "M10", "length": 50, "material": "stainless A4", "coating": None},
        {"standard": "DIN 7985", "size": "M4", "length": 12, "material": None, "coating": "zinc plated"},
        {"standard": "DIN 603", "size": "M8", "length": 40, "material": None, "coating": None},
        {"standard": "DIN 934", "size": "M6", "length": None, "material": None, "coating": "zinc plated"},
        {"standard": "DIN 125-A", "size": "M10", "length": None, "material": "stainless A2", "coating": None},
    ]
    assert canonicalize(lines) == expected


def test_set_b_messy_vendor_synonyms():
    lines = [
        "DIN 931 Hex Bolt M6x30 CL8.8 ZnPl",
        "ISO4762 Socket cap M5x16 stainless",
        "Washer M10 SS A2 DIN 125",
        "Hex nut M6 zinc plated",
        "Carriage bolt M8x40 low tensile DIN 603",
    ]
    expected = [
        {"standard": "DIN 931", "size": "M6", "length": 30, "material": None, "coating": "zinc plated"},
        {"standard": "ISO 4762", "size": "M5", "length": 16, "material": "stainless", "coating": None},
        {"standard": "DIN 125", "size": "M10", "length": None, "material": "stainless A2", "coating": None},
        {"standard": None, "size": "M6", "length": None, "material": None, "coating": "zinc plated"},
        {"standard": "DIN 603", "size": "M8", "length": 40, "material": None, "coating": None},
    ]
    assert canonicalize(lines) == expected


def test_set_c_null_discipline():
    lines = [
        "M6x30",
        "DIN934",
        "ZP A2",
        "DIN 603 4.6",
    ]
    expected = [
        {"standard": None, "size": "M6", "length": 30, "material": None, "coating": None},
        {"standard": "DIN 934", "size": None, "length": None, "material": None, "coating": None},
        {"standard": None, "size": None, "length": None, "material": "stainless A2", "coating": "zinc plated"},
        {"standard": "DIN 603", "size": None, "length": None, "material": None, "coating": None},
    ]
    assert canonicalize(lines) == expected
