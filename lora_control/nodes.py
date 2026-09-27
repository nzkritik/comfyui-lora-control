"""ComfyUI nodes for building and applying LoRA stacks.

Every node passes a LORA_STACK along, the list of (lora_name, model_strength,
clip_strength) tuples used by the Comfyroll and Efficiency stack nodes, so
they chain with each other and with those packs. Nothing is loaded until
Apply LoRA Stack.

Written against ComfyUI's V3 node API (comfy_api.latest). The node ids and
input names are the same as the first, classic-API release, so saved
workflows keep loading.
"""

import logging

import comfy.sd
import comfy.utils
import folder_paths
from comfy_api.latest import io

from . import selection as sel

logger = logging.getLogger(__name__)

CATEGORY = "loaders/LoRA Control"
SLOTS = 6
NONE = "None"

LoraStack = io.Custom("LORA_STACK")

SEED_TOOLTIP = ("Random: the same seed always picks the same LoRA. Sequence: the position in the "
                "sorted list, so set this to increment to take the next LoRA on every run.")
MODE_TOOLTIP = "random: a seeded random pick. sequence: each LoRA in name order, one per run."


def lora_list():
    return folder_paths.get_filename_list("loras")


def strength_input(id):
    return io.Float.Input(id, default=1.0, min=-10.0, max=10.0, step=0.01)


def picker_inputs():
    """The strength, mode and seed every picker shares."""
    return [
        strength_input("strength"),
        io.Combo.Input("mode", options=list(sel.MODES), default="random", tooltip=MODE_TOOLTIP),
        io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                     tooltip=SEED_TOOLTIP),
    ]


def stack_input():
    return LoraStack.Input("lora_stack", optional=True, tooltip="Chain another stack in; its LoRAs come first.")


def extend(stack, entries):
    return list(stack or []) + entries


def summary(entries):
    return ", ".join(f"{sel.display_name(n)}:{m:g}" for n, m, _ in entries)


def picked(candidates, stack, mode, seed, what):
    if not candidates:
        raise ValueError(f"LoRA Control: no LoRA {what}")
    if mode == "random":
        # Prefer LoRAs not already in the incoming stack, so two pickers do not
        # land on the same file. Sequence keeps the full list, or skipping
        # would shift the order being stepped through.
        used = {n for n, _, _ in (stack or [])}
        fresh = [c for c in candidates if c not in used]
        candidates = fresh or candidates
    return sel.pick(candidates, mode, seed)


class LoRAStack(io.ComfyNode):
    """Up to six chosen LoRAs, each with its own on/off and strength."""

    @classmethod
    def define_schema(cls):
        loras = [NONE] + lora_list()
        inputs = [io.Boolean.Input("enabled", default=True, tooltip="Off passes the incoming stack through untouched.")]
        for i in range(1, SLOTS + 1):
            inputs += [
                io.Boolean.Input(f"on_{i}", default=True),
                io.Combo.Input(f"lora_{i}", options=loras),
                strength_input(f"strength_{i}"),
            ]
        return io.Schema(
            node_id="LoRAControlStack",
            display_name="LoRA Stack (LoRA Control)",
            category=CATEGORY,
            description="Pick up to six LoRAs with a strength each. Chain another stack in to go past six.",
            inputs=inputs + [stack_input()],
            outputs=[LoraStack.Output("lora_stack"), io.String.Output("loras")],
        )

    @classmethod
    def execute(cls, enabled, lora_stack=None, **slots):
        if not enabled:
            return io.NodeOutput(extend(lora_stack, []), "")
        entries = []
        for i in range(1, SLOTS + 1):
            name, strength = slots.get(f"lora_{i}", NONE), slots.get(f"strength_{i}", 1.0)
            if slots.get(f"on_{i}", True) and name != NONE and strength != 0:
                entries.append((name, strength, strength))
        return io.NodeOutput(extend(lora_stack, entries), summary(entries))


class LoRAByName(io.ComfyNode):
    """One LoRA whose name contains a pattern, such as "char-"."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LoRAControlByName",
            display_name="LoRA by Name (LoRA Control)",
            category=CATEGORY,
            description="Pick one LoRA whose name matches a pattern, at random or in sequence.",
            inputs=[
                io.Boolean.Input("enabled", default=True),
                io.String.Input("pattern", default="", tooltip=(
                    "Part of the file name, any case. Wildcards (* ? [..]) match the whole name "
                    "instead: style-a* is every LoRA whose name starts with style-a.")),
                *picker_inputs(),
                io.Boolean.Input("match_folder", default=False,
                                 tooltip="Also match the folder, so characters/ selects everything in that folder."),
                stack_input(),
            ],
            outputs=[LoraStack.Output("lora_stack"), io.String.Output("lora")],
        )

    @classmethod
    def execute(cls, enabled, pattern, strength, mode, seed, match_folder, lora_stack=None):
        if not enabled:
            return io.NodeOutput(extend(lora_stack, []), "")
        if not pattern.strip():
            raise ValueError("LoRA Control: LoRA by Name needs a pattern, part of a LoRA's file name")
        candidates = sel.matching(lora_list(), pattern, match_path=match_folder)
        name = picked(candidates, lora_stack, mode, seed, f"matches the pattern {pattern!r}")
        entries = [(name, strength, strength)]
        return io.NodeOutput(extend(lora_stack, entries), summary(entries))


class LoRAFromFolder(io.ComfyNode):
    """One LoRA from a folder, optionally including its subfolders."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LoRAControlFromFolder",
            display_name="LoRA from Folder (LoRA Control)",
            category=CATEGORY,
            description="Pick one LoRA from a folder of the loras directory, at random or in sequence.",
            inputs=[
                io.Boolean.Input("enabled", default=True),
                io.Combo.Input("folder", options=sel.list_folders(lora_list())),
                io.Boolean.Input("include_subfolders", default=False),
                *picker_inputs(),
                stack_input(),
            ],
            outputs=[LoraStack.Output("lora_stack"), io.String.Output("lora")],
        )

    @classmethod
    def execute(cls, enabled, folder, include_subfolders, strength, mode, seed, lora_stack=None):
        if not enabled:
            return io.NodeOutput(extend(lora_stack, []), "")
        candidates = sel.in_folder(lora_list(), folder, include_subfolders)
        where = f"in {folder}" + (" or its subfolders" if include_subfolders else "")
        name = picked(candidates, lora_stack, mode, seed, where)
        entries = [(name, strength, strength)]
        return io.NodeOutput(extend(lora_stack, entries), summary(entries))


# V3 nodes are classes, not instances, so Apply's file cache lives here.
_lora_cache = {}


def load_lora(name):
    path = folder_paths.get_full_path_or_raise("loras", name)
    if path not in _lora_cache:
        _lora_cache[path] = comfy.utils.load_torch_file(path, safe_load=True)
    return path, _lora_cache[path]


class ApplyLoRAStack(io.ComfyNode):
    """Load every LoRA in a stack onto the model, and the CLIP if given."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LoRAControlApply",
            display_name="Apply LoRA Stack (LoRA Control)",
            category=CATEGORY,
            description="Apply a LoRA stack. Leave CLIP unconnected for model-only LoRAs.",
            inputs=[
                io.Model.Input("model"),
                LoraStack.Input("lora_stack"),
                io.Clip.Input("clip", optional=True),
            ],
            outputs=[io.Model.Output("model"), io.Clip.Output("clip"), io.String.Output("loras")],
        )

    @classmethod
    def execute(cls, model, lora_stack, clip=None):
        global _lora_cache
        used = set()
        for name, model_strength, clip_strength in lora_stack or []:
            if model_strength == 0 and (clip is None or clip_strength == 0):
                continue
            path, lora = load_lora(name)
            used.add(path)
            model, clip = comfy.sd.load_lora_for_models(
                model, clip, lora, model_strength, clip_strength if clip is not None else 0)
            logger.info("LoRA Control: applied %s (model %g, clip %g)", name, model_strength,
                        clip_strength if clip is not None else 0)
        # Keep only what this stack used, so a long session does not hold every
        # LoRA it has ever seen in RAM.
        _lora_cache = {p: l for p, l in _lora_cache.items() if p in used}
        return io.NodeOutput(model, clip, summary(lora_stack or []))


NODES = [LoRAStack, LoRAByName, LoRAFromFolder, ApplyLoRAStack]
