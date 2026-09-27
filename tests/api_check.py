"""Drive the builder nodes through a running ComfyUI's HTTP API.

    python3 tests/api_check.py [http://127.0.0.1:8189]

Run it against a ComfyUI started on the dummy LoRAs from
tests/make_test_base.py. No model is needed: each prompt ends in core's
PreviewAny, and the STRING it received is read back from /history. Checks
picks, sequence order, the subfolder switch, chaining, random de-duplication
and the error messages.
"""

import json
import sys
import time
import urllib.request
import uuid

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8189"
CLIENT = str(uuid.uuid4())


def post(path, body):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        return json.load(e)


def get(path):
    return json.load(urllib.request.urlopen(URL + path))


def run(graph):
    """Queue a prompt; return (strings seen by each PreviewAny, error message)."""
    resp = post("/prompt", {"prompt": graph, "client_id": CLIENT})
    if "prompt_id" not in resp:
        return None, json.dumps(resp.get("error") or resp)[:300]
    pid = resp["prompt_id"]
    for _ in range(300):
        hist = get(f"/history/{pid}").get(pid)
        if hist and hist.get("status", {}).get("completed") is not None:
            break
        time.sleep(0.1)
    status = hist["status"]
    if status.get("status_str") == "error":
        msgs = [m[1].get("exception_message", "") for m in status.get("messages", []) if m[0] == "execution_error"]
        return None, " | ".join(msgs)
    out = {}
    for node_id, o in hist["outputs"].items():
        out[node_id] = o.get("text", [""])[0]
    return out, None


def by_name(pattern, mode="random", seed=0, stack=None, strength=1.0):
    n = {"class_type": "LoRAControlByName", "inputs": {
        "enabled": True, "pattern": pattern, "strength": strength, "mode": mode, "seed": seed, "match_folder": False}}
    if stack:
        n["inputs"]["lora_stack"] = stack
    return n


def folder(name, sub, mode="random", seed=0, stack=None):
    n = {"class_type": "LoRAControlFromFolder", "inputs": {
        "enabled": True, "folder": name, "include_subfolders": sub, "strength": 0.8, "mode": mode, "seed": seed}}
    if stack:
        n["inputs"]["lora_stack"] = stack
    return n


def preview(src, idx=1):
    return {"class_type": "PreviewAny", "inputs": {"source": [src, idx]}}


def one(node):
    out, err = run({"1": node, "9": preview("1")})
    return err if err else out["9"]


failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


# random: reproducible per seed, varies across seeds, only char- files
picks = [one(by_name("char-", seed=s)) for s in (11, 11, 12, 13, 14)]
check("random is reproducible for a seed", picks[0] == picks[1], picks[0])
check("random varies across seeds", len(set(picks[1:])) > 1, ", ".join(picks[1:]))
check("random only picks char- LoRAs", all(p.startswith("char-") for p in picks), "")

# sequence: consecutive seeds walk the sorted list and wrap
seq = [one(by_name("char-A", mode="sequence", seed=s)) for s in range(3)]
check("sequence walks in order and wraps", seq == ["char-Alice:1", "char-Anna:1", "char-Alice:1"], ", ".join(seq))

# folder: subfolder switch
flat = {one(folder("characters", False, mode="sequence", seed=s)) for s in range(12)}
deep = {one(folder("characters", True, mode="sequence", seed=s)) for s in range(12)}
extra = {one(folder("characters/extra", False, mode="sequence", seed=s)) for s in range(3)}
check("include_subfolders adds the subfolder's LoRAs",
      len(flat) == 5 and len(deep) == 6 and extra <= deep and not (extra & flat),
      f"flat {len(flat)}, deep {len(deep)}, extra {sorted(extra)}")

# chain: stack -> by name -> folder, and the summary reflects all of it
graph = {
    "1": {"class_type": "LoRAControlStack", "inputs": {"enabled": True, **{
        k: v for i in range(1, 7) for k, v in
        ((f"on_{i}", True), (f"lora_{i}", "characters/char-Anna.safetensors" if i == 1 else "None"), (f"strength_{i}", 0.7))}}},
    "2": by_name("char-A", seed=5, stack=["1", 0]),
    "3": folder("styles", False, seed=5, stack=["2", 0]),
    "4": {"class_type": "LoRAControlApply", "inputs": {"model": ["5", 0], "lora_stack": ["3", 0]}},
}
# No model loaded here, so read the chain back through each node's summary instead.
chain = {"1": graph["1"], "2": graph["2"], "3": graph["3"],
         "8": preview("1"), "9": preview("2"), "10": preview("3")}
out, err = run(chain)
check("chain runs", err is None, err or "")
if out:
    check("stack summary", out["8"] == "char-Anna:0.7", out["8"])
    check("random skips a LoRA already in the stack", out["9"] == "char-Alice:1", out["9"])
    check("folder pick is from styles", out["10"].startswith("style-") and out["10"].endswith(":0.8"), out["10"])

# disabled passes through, blank summary
n = by_name("char-", seed=1)
n["inputs"]["enabled"] = False
check("disabled node outputs nothing", one(n) == "", repr(one(n)))

# no match is an error that names the pattern
err = one(by_name("no-such-lora-xyz"))
check("no match is a named error", "no-such-lora-xyz" in err, err[:120])

# a blank pattern says what is missing instead of "no match for ''"
err = one(by_name("  "))
check("blank pattern is a clear error", "needs a pattern" in err, err[:120])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
