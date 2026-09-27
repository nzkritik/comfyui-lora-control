// Keeps the seed's "control after generate" in step with the mode, so the
// pickers do what their mode says without a second setting to remember:
// random -> randomize (a new pick every run), sequence -> increment (the next
// LoRA every run). Only on a change of mode, or for a node just added, so a
// saved workflow keeps whatever its seed control was saved with.
import { app } from "../../scripts/app.js";

const PICKERS = new Set(["LoRAControlByName", "LoRAControlFromFolder"]);
const CONTROL_FOR = { random: "randomize", sequence: "increment" };

function seedControl(node) {
  const seed = node.widgets?.find((w) => w.name === "seed");
  return (
    seed?.linkedWidgets?.find((w) => w.name === "control_after_generate") ??
    node.widgets?.find((w) => w.name === "control_after_generate")
  );
}

function syncControl(node, mode) {
  const control = seedControl(node);
  const wanted = CONTROL_FOR[mode];
  if (!control || !wanted || control.value === wanted) return;
  control.value = wanted;
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "lora_control.seed_follows_mode",
  nodeCreated(node) {
    if (!PICKERS.has(node.comfyClass)) return;
    const mode = node.widgets?.find((w) => w.name === "mode");
    if (!mode) return;
    const original = mode.callback;
    mode.callback = function (value, ...rest) {
      const result = original?.call(this, value, ...rest);
      syncControl(node, value);
      return result;
    };
    // A node just added gets the default mode's control; a loaded one is
    // configured after this and keeps its saved value.
    syncControl(node, mode.value);
  },
});
