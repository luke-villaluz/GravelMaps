// "New version available" in the packaged Mac app: checks GitHub when online, installs on a click.

import { $, esc } from "./util.js";
import { net, onNetChange } from "./online.js";

let checked = false;

async function check() {
  if (checked || !net.online) return;
  checked = true;
  try {
    const info = await (await fetch("/api/setup/update")).json();
    if (!info.newer) return;
    const box = $("update-note");
    box.innerHTML = `<b>GravelMaps ${esc(info.latest)} is available.</b> You have ${esc(info.current)}.
      ${info.problem ? `<div class="sub">${esc(info.problem)}</div>`
        : `<div class="row"><button id="update-go">Update now</button>${info.notes ? `<a href="${esc(info.notes)}" target="_blank" rel="noopener">What's new</a>` : ""}</div>`}
      <div class="sub" id="update-state"></div>`;
    box.hidden = false;
    $("update-go")?.addEventListener("click", install);
  } catch {
    checked = false; // try again when the connection comes back
  }
}

async function install() {
  $("update-go").disabled = true;
  const res = await fetch("/api/setup/update", { method: "POST" });
  if (!res.ok) { $("update-state").textContent = (await res.json()).detail; $("update-go").disabled = false; return; }
  const timer = setInterval(async () => {
    const s = await (await fetch("/api/setup/update/status")).json().catch(() => null);
    if (!s) return; // the app is restarting
    const pct = s.total_bytes ? ` ${Math.round((100 * s.done_bytes) / s.total_bytes)}%` : "";
    $("update-state").textContent = { downloading: `Downloading the update…${pct}`, installing: "Installing…",
      restarting: "Restarting GravelMaps…", failed: s.error }[s.state] || "";
    if (s.state === "failed") { clearInterval(timer); $("update-go").disabled = false; }
  }, 700);
}

export function initUpdate() {
  check();
  onNetChange(check);
}
