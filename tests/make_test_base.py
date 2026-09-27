"""Build a throwaway ComfyUI base directory for the API and UI checks.

    python3 tests/make_test_base.py /tmp/lc-base

Creates models/loras with empty dummy LoRA files (the picker nodes only read
names, so the files never need to be real) and links this repo into
custom_nodes. Then start a second ComfyUI that sees nothing else:

    cd /path/to/ComfyUI
    python main.py --cpu --port 8189 --base-directory /tmp/lc-base \\
        --disable-all-custom-nodes --whitelist-custom-nodes comfyui-lora-control \\
        --database-url sqlite:///:memory:

and run tests/api_check.py and tests/ui_check.mjs against port 8189.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LORAS = [
    "detail-slider.safetensors",
    "characters/char-Alice.safetensors",
    "characters/char-Anna.safetensors",
    "characters/char-Bella.safetensors",
    "characters/char-Clara.safetensors",
    "characters/char-Dora.safetensors",
    "characters/extra/char-Extra.safetensors",
    "styles/style-ink.safetensors",
    "styles/style-oil.safetensors",
    "styles/style-watercolor.safetensors",
]


def main(base):
    loras = os.path.join(base, "models", "loras")
    for name in LORAS:
        path = os.path.join(loras, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
    nodes = os.path.join(base, "custom_nodes")
    os.makedirs(nodes, exist_ok=True)
    link = os.path.join(nodes, "comfyui-lora-control")
    if not os.path.lexists(link):
        os.symlink(REPO, link, target_is_directory=True)
    for sub in ("user", "input", "output", "temp"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    print(f"{len(LORAS)} dummy LoRAs in {loras}; {link} -> {REPO}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]))
