import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from lora_control import selection as sel

LORAS = [
    "detail-slider.safetensors",
    "characters/char-AliceWood.safetensors",
    "characters/char-AnnaPark.safetensors",
    "characters/CHAR-uppercase.safetensors",
    "characters/Age-Slider.safetensors",
    "characters/tools/char-ToolOne.safetensors",
    "styles/char-NotReally.safetensors",
    "styles\\ink-style.safetensors",
    "deep/only/nested.safetensors",
]


def test_folders_include_parents_and_root():
    assert sel.list_folders(LORAS) == ["(root)", "characters", "characters/tools", "deep", "deep/only", "styles"]


def test_folder_without_subfolders():
    got = sel.in_folder(LORAS, "characters", False)
    assert got == [
        "characters/Age-Slider.safetensors",
        "characters/char-AliceWood.safetensors",
        "characters/char-AnnaPark.safetensors",
        "characters/CHAR-uppercase.safetensors",
    ]


def test_folder_with_subfolders():
    assert "characters/tools/char-ToolOne.safetensors" in sel.in_folder(LORAS, "characters", True)
    assert len(sel.in_folder(LORAS, "characters", True)) == 5


def test_folder_prefix_is_not_a_subfolder():
    # "characters" must not swallow a sibling folder called "characters2".
    names = LORAS + ["characters2/other.safetensors"]
    assert "characters2/other.safetensors" not in sel.in_folder(names, "characters", True)


def test_folder_with_only_subfolders():
    assert sel.in_folder(LORAS, "deep", False) == []
    assert sel.in_folder(LORAS, "deep", True) == ["deep/only/nested.safetensors"]


def test_root_folder():
    assert sel.in_folder(LORAS, "(root)", False) == ["detail-slider.safetensors"]
    assert len(sel.in_folder(LORAS, "(root)", True)) == len(LORAS)


def test_windows_separators():
    # sorted case-insensitively on the normalized path: char-notreally < ink-style
    assert sel.in_folder(LORAS, "styles", False) == ["styles/char-NotReally.safetensors", "styles\\ink-style.safetensors"]


def test_partial_name_is_case_insensitive_and_file_name_only():
    got = sel.matching(LORAS, "char-")
    assert "characters/CHAR-uppercase.safetensors" in got  # any case
    assert "styles/char-NotReally.safetensors" in got
    assert len(got) == 5
    # the folder name "characters" is not part of the file name
    assert sel.matching(LORAS, "characters") == []


def test_match_path_includes_folders():
    assert len(sel.matching(LORAS, "characters/", match_path=True)) == 5


def test_wildcards_match_whole_name():
    assert sel.matching(LORAS, "char-A*") == [
        "characters/char-AliceWood.safetensors",
        "characters/char-AnnaPark.safetensors",
    ]
    assert sel.matching(LORAS, "*wood") == ["characters/char-AliceWood.safetensors"]
    assert sel.matching(LORAS, "wood*") == []


def test_blank_pattern_matches_nothing():
    assert sel.matching(LORAS, "   ") == []


def test_sequence_walks_in_order_and_wraps():
    c = ["a", "b", "c"]
    assert [sel.pick(c, "sequence", s) for s in range(5)] == ["a", "b", "c", "a", "b"]


def test_random_is_reproducible_and_covers_all():
    c = [f"l{i}" for i in range(10)]
    assert sel.pick(c, "random", 1234) == sel.pick(c, "random", 1234)
    assert len({sel.pick(c, "random", s) for s in range(200)}) == 10


def test_pick_errors():
    with pytest.raises(ValueError):
        sel.pick([], "random", 0)
    with pytest.raises(ValueError):
        sel.pick(["a"], "shuffle", 0)


def test_display_name():
    assert sel.display_name("characters/char-AnnaPark.safetensors") == "char-AnnaPark"
    assert sel.display_name("styles\\ink-style.safetensors") == "ink-style"
