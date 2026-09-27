"""Does Apply LoRA Stack load a Z-Image LoRA completely?

    python3 tests/zimage_check.py --lora characters/my-lora.safetensors \
        [--url http://127.0.0.1:8188] [--model ...] [--clip ...] [--vae ...]

Renders one prompt and seed three ways on a real Z-Image Turbo model:
  A  no LoRA
  B  the LoRA, picked by LoRA by Name and applied by Apply LoRA Stack
     (ComfyUI's own loader)
  C  the same LoRA through ZImageTurboLoraStackV4, which translates the
     LoRA's keys itself
and reads ComfyUI's log for "lora key not loaded" during each run. B should
log nothing, differ clearly from A, and match C closely.

Needs a ComfyUI with Z-Image Turbo, a Z-Image LoRA and the ZImageTurboLoraStackV4
node (for C). The model defaults are the file names from ComfyUI's own Z-Image
Turbo template.
"""

import argparse
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid

from PIL import Image, ImageChops, ImageStat

args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
args.add_argument("--url", default="http://127.0.0.1:8188")
args.add_argument("--model", default="z_image_turbo_bf16.safetensors")
args.add_argument("--clip", default="qwen_3_4b.safetensors")
args.add_argument("--vae", default="ae.safetensors")
args.add_argument("--lora", required=True, help="a Z-Image LoRA, as listed in ComfyUI (folder/name.safetensors)")
args = args.parse_args()
URL, MODEL, CLIP, VAE, LORA = args.url, args.model, args.clip, args.vae, args.lora
PROMPT = "photo portrait of a woman sitting at a cafe table, natural window light, 50mm"
SEED = 424242


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data, {"Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        raw = e.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")


def log_text():
    logs = call("/internal/logs")
    return logs if isinstance(logs, str) else json.dumps(logs)


def base(model_ref, clip_ref, prefix):
    return {
        "10": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model_ref, "shift": 3.0}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": PROMPT}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": ""}},
        "13": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "14": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["11", 0], "negative": ["12", 0], "latent_image": ["13", 0],
            "seed": SEED, "steps": 8, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["3", 0]}},
        "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": prefix}},
    }


LOADERS = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "lumina2", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
}


def graph_a():
    return {**LOADERS, **base(["1", 0], ["2", 0], "lora-control-test/A-none")}


def graph_b():
    stem = LORA.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {**LOADERS,
            "4": {"class_type": "LoRAControlByName", "inputs": {
                "enabled": True, "pattern": stem, "strength": 1.0, "mode": "sequence", "seed": 0, "match_folder": False}},
            "5": {"class_type": "LoRAControlApply", "inputs": {"model": ["1", 0], "clip": ["2", 0], "lora_stack": ["4", 0]}},
            "20": {"class_type": "PreviewAny", "inputs": {"source": ["5", 2]}},
            **base(["5", 0], ["5", 1], "lora-control-test/B-lora-control")}


def graph_c():
    return {**LOADERS,
            "6": {"class_type": "ZImageTurboLoraStackV4", "inputs": {
                "model": ["1", 0], "clip": ["2", 0], "lora_count": 1, "toggle_all": True,
                "enabled_1": True, "lora_name_1": LORA, "strength_1": 1.0}},
            **base(["6", 0], ["6", 1], "lora-control-test/C-v4")}


def run(label, graph):
    before = len(log_text())
    resp = call("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    if "prompt_id" not in resp:
        sys.exit(f"{label}: rejected: {json.dumps(resp)[:400]}")
    pid = resp["prompt_id"]
    t0 = time.time()
    while True:
        hist = call(f"/history/{pid}").get(pid)
        if hist and hist["status"].get("completed") is not None:
            break
        time.sleep(1)
    status = hist["status"]
    if status.get("status_str") == "error":
        msgs = [m[1] for m in status["messages"] if m[0] == "execution_error"]
        sys.exit(f"{label}: failed: {json.dumps(msgs)[:600]}")
    img = hist["outputs"]["16"]["images"][0]
    path = f"{img['subfolder']}/{img['filename']}"
    new_log = log_text()[before:]
    skipped = new_log.count("lora key not loaded")
    picked = hist["outputs"].get("20", {}).get("text", [""])[0]
    print(f"{label}: {time.time() - t0:5.1f}s  {path}  skipped-keys={skipped}" + (f"  picked={picked}" if picked else ""))
    if skipped:
        print("   first:", new_log[new_log.index("lora key not loaded"):][:160].replace("\\n", " "))
    return path, skipped


def fetch(path):
    """An output image, read through the server so any output folder works."""
    subfolder, filename = path.rsplit("/", 1)
    query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    return Image.open(io.BytesIO(urllib.request.urlopen(f"{URL}/view?{query}").read())).convert("RGB")


def diff(a, b):
    ia, ib = fetch(a), fetch(b)
    return sum(ImageStat.Stat(ImageChops.difference(ia, ib)).mean) / 3


a, _ = run("A no LoRA      ", graph_a())
b, skipped_b = run("B LoRA Control ", graph_b())
c, skipped_c = run("C V4 stack     ", graph_c())
print(f"\nmean pixel difference (0-255):  A-B {diff(a, b):.2f}   A-C {diff(a, c):.2f}   B-C {diff(b, c):.2f}")
ok = skipped_b == 0 and diff(a, b) > 5 * max(diff(b, c), 0.5)
print("RESULT:", "PASS: complete load, matches V4" if ok else "CHECK: see numbers above")
