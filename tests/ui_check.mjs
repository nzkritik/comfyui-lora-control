// Frontend check for js/lora_control.js, in headless Chromium over CDP.
//
//   node tests/ui_check.mjs [http://127.0.0.1:8189]
//
// Adds each picker node, flips its mode as the dropdown would, and checks the
// seed's control follows; then saves and reloads a workflow whose control was
// set by hand, to prove loading never overwrites a saved value.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const URL = process.argv[2] ?? "http://127.0.0.1:8189";
const PORT = 9333;
const profile = mkdtempSync(join(tmpdir(), "lc-chrome-"));
const chrome = spawn("chromium", [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1600,1000", "--no-first-run", URL,
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, seq = 0;
const pending = new Map();

async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = targets.find((t) => t.type === "page");
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
        ws.onmessage = (m) => {
          const msg = JSON.parse(m.data);
          if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
        };
        return;
      }
    } catch {}
    await sleep(200);
  }
  throw new Error("no chromium page");
}

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((r) => pending.set(id, r));
}

async function evaluate(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  return r.result?.result?.value;
}

const failures = [];
function check(label, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${label}${detail ? `  [${detail}]` : ""}`);
  if (!ok) failures.push(label);
}

try {
  await connect();
  // Wait for the app and our extension to be registered.
  for (let i = 0; i < 150; i++) {
    const ready = await evaluate(`!!(window.app?.graph && window.app.extensions?.some(e => e.name === "lora_control.seed_follows_mode"))`);
    if (ready) break;
    await sleep(200);
  }
  check("extension registered", await evaluate(`window.app.extensions.some(e => e.name === "lora_control.seed_follows_mode")`));

  for (const type of ["LoRAControlByName", "LoRAControlFromFolder"]) {
    const r = await evaluate(`(() => {
      const app = window.app;
      app.graph.clear();
      const n = LiteGraph.createNode(${JSON.stringify(type)});
      app.graph.add(n);
      const ctl = () => {
        const seed = n.widgets.find(w => w.name === "seed");
        return (seed.linkedWidgets?.find(w => w.name === "control_after_generate")
          ?? n.widgets.find(w => w.name === "control_after_generate"))?.value;
      };
      const mode = n.widgets.find(w => w.name === "mode");
      const out = { initialMode: mode.value, initial: ctl() };
      mode.value = "sequence"; mode.callback?.("sequence");
      out.sequence = ctl();
      mode.value = "random"; mode.callback?.("random");
      out.random = ctl();
      return out;
    })()`);
    check(`${type}: new node defaults to random + randomize`, r.initialMode === "random" && r.initial === "randomize", JSON.stringify(r));
    check(`${type}: sequence switches to increment`, r.sequence === "increment", r.sequence);
    check(`${type}: random switches back to randomize`, r.random === "randomize", r.random);
  }

  // A saved control value survives a reload untouched.
  const reload = await evaluate(`(async () => {
    const app = window.app;
    app.graph.clear();
    const n = LiteGraph.createNode("LoRAControlByName");
    app.graph.add(n);
    const mode = n.widgets.find(w => w.name === "mode");
    mode.value = "sequence"; mode.callback?.("sequence");
    const seed = n.widgets.find(w => w.name === "seed");
    const ctl = seed.linkedWidgets?.find(w => w.name === "control_after_generate") ?? n.widgets.find(w => w.name === "control_after_generate");
    ctl.value = "fixed";
    seed.value = 42;
    const saved = JSON.parse(JSON.stringify(app.graph.serialize()));
    await app.loadGraphData(saved);
    const m = app.graph._nodes.find(x => x.comfyClass === "LoRAControlByName");
    const s = m.widgets.find(w => w.name === "seed");
    const c = s.linkedWidgets?.find(w => w.name === "control_after_generate") ?? m.widgets.find(w => w.name === "control_after_generate");
    const prompt = (await app.graphToPrompt()).output;
    return { mode: m.widgets.find(w => w.name === "mode").value, control: c.value, seed: s.value,
             prompt: Object.values(prompt)[0]?.inputs };
  })()`);
  check("reload keeps mode", reload.mode === "sequence", reload.mode);
  check("reload keeps a hand-set control", reload.control === "fixed", reload.control);
  check("reload keeps the seed", reload.seed === 42, String(reload.seed));
  check("prompt carries mode and seed", reload.prompt?.mode === "sequence" && reload.prompt?.seed === 42, JSON.stringify(reload.prompt));
} catch (e) {
  failures.push(String(e));
  console.log("ERROR", e.message);
} finally {
  ws?.close();
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
console.log(`\n${failures.length} failure(s)`);
process.exit(failures.length ? 1 : 0);
