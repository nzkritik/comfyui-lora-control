from typing_extensions import override

from comfy_api.latest import ComfyExtension, io

from .lora_control.nodes import NODES

WEB_DIRECTORY = "./js"


class LoRAControlExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return NODES


async def comfy_entrypoint() -> LoRAControlExtension:
    return LoRAControlExtension()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
