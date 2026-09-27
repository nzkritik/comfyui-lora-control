"""Choosing LoRAs from ComfyUI's list of LoRA files.

Pure functions over the relative paths ComfyUI reports for the "loras"
folder ("characters/char-Name.safetensors"), so this module imports nothing from
ComfyUI and can be tested on its own.
"""

import fnmatch
import random

ROOT_FOLDER = "(root)"

MODES = ("random", "sequence")


def normalize(path):
    """ComfyUI reports paths with the OS separator; compare with '/'."""
    return path.replace("\\", "/")


def folder_of(path):
    path = normalize(path)
    return path.rsplit("/", 1)[0] if "/" in path else ""


def list_folders(lora_names):
    """Every folder that holds a LoRA, and every folder above one, sorted.

    Parents are included so a folder holding only subfolders can still be
    picked with include_subfolders on.
    """
    folders = set()
    for name in lora_names:
        folder = folder_of(name)
        while folder:
            folders.add(folder)
            folder = folder_of(folder)
    return [ROOT_FOLDER] + sorted(folders, key=str.lower)


def in_folder(lora_names, folder, include_subfolders):
    """LoRAs directly in `folder`, or anywhere beneath it with include_subfolders."""
    target = "" if folder == ROOT_FOLDER else normalize(folder).strip("/")
    out = []
    for name in lora_names:
        parent = folder_of(name)
        if parent == target:
            out.append(name)
        elif include_subfolders and (target == "" or parent.startswith(target + "/")):
            out.append(name)
    return sorted(out, key=lambda n: normalize(n).lower())


def has_wildcards(pattern):
    return any(c in pattern for c in "*?[")


def matching(lora_names, pattern, match_path=False):
    """LoRAs whose file name contains `pattern`, ignoring case.

    With wildcards (* ? [..]) the pattern must match the whole name instead,
    so "char-*" and "char-" pick the same files but "*Wood*" can anchor nothing.
    match_path tests the folder too, so "characters/" selects a folder by name.
    """
    pattern = pattern.strip().lower()
    if not pattern:
        return []
    wild = has_wildcards(pattern)
    out = []
    for name in lora_names:
        subject = normalize(name) if match_path else normalize(name).rsplit("/", 1)[-1]
        subject = subject.lower()
        if wild:
            stem = subject.rsplit(".", 1)[0]
            hit = fnmatch.fnmatchcase(subject, pattern) or fnmatch.fnmatchcase(stem, pattern)
        else:
            hit = pattern in subject
        if hit:
            out.append(name)
    return sorted(out, key=lambda n: normalize(n).lower())


def pick(candidates, mode, seed):
    """One LoRA from `candidates` (already sorted).

    random:   a seeded choice, so the same seed always picks the same LoRA and
              an old workflow reproduces its image.
    sequence: candidates in order, seed modulo the count; with the seed
              widget on "increment" each run takes the next one and wraps.
    """
    if not candidates:
        raise ValueError("no LoRAs to choose from")
    if mode == "sequence":
        return candidates[seed % len(candidates)]
    if mode == "random":
        return random.Random(seed).choice(candidates)
    raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")


def display_name(path):
    """File name without folder or extension, for the summary output."""
    name = normalize(path).rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name
