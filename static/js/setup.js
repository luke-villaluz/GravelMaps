// The setup screen (setup.html): pick states, then follow the download and build steps.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const size = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${Math.round(b / 1e6)} MB`);

let states = [];
const chosen = new Set();
let lastRequest = null;
let poller = null;

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function renderStates() {
  const q = $("filter").value.trim().toLowerCase();
  $("states").innerHTML = states.filter((s) => !q || s.name.toLowerCase().includes(q) || s.code === q).map((s) =>
    `<label class="${chosen.has(s.code) ? "on" : ""}"><input type="checkbox" value="${s.code}"${chosen.has(s.code) ? " checked" : ""}>${esc(s.name)}<span class="code">${s.code}</span></label>`).join("");
  $("states").querySelectorAll("input").forEach((box) => box.addEventListener("change", () => {
    if (box.checked) chosen.add(box.value);
    else chosen.delete(box.value);
    box.parentElement.classList.toggle("on", box.checked);
    renderChosen();
  }));
}

function renderChosen() {
  const names = states.filter((s) => chosen.has(s.code)).map((s) => s.name);
  $("chosen").textContent = names.length ? `Selected: ${names.join(", ")}` : "No states selected yet.";
  $("start").disabled = !names.length;
}

function showPick(status) {
  $("pick").hidden = false;
  $("run").hidden = true;
  const ready = status.ready;
  $("back").hidden = !ready;
  $("update").hidden = !ready;
  $("finish-box").hidden = !(ready && status.pending.length);
  $("finish-list").textContent = status.pending.join(", ");
  $("start").textContent = ready ? "Switch to these states" : "Download and set up";
  if (ready) $("pick-lead").textContent = "Change which states GravelMaps covers, or update the map data you have. Your current map keeps working until the new one is ready.";
  renderStates();
  renderChosen();
}

function stepIcon(state) {
  return { done: "✓", failed: "✕", running: '<span class="spin"></span>', todo: "○" }[state] || "○";
}

function renderRun(status) {
  const job = status.job;
  $("pick").hidden = true;
  $("run").hidden = false;
  $("steps").innerHTML = job.steps.map((s) => {
    const live = s.state === "running";
    const bytes = live && job.total_bytes ? `<div class="bar"><i style="width:${(100 * job.done_bytes / job.total_bytes).toFixed(1)}%"></i></div>
      <div class="detail">${size(job.done_bytes)} of ${size(job.total_bytes)}</div>` : "";
    const detail = live && !job.total_bytes && job.detail ? `<div class="detail">${esc(job.detail)}</div>` : "";
    return `<li class="${s.state}"><span class="icon">${stepIcon(s.state)}</span><div style="flex:1"><div class="title">${esc(s.title)}</div>${bytes}${detail}</div></li>`;
  }).join("") || "<li class=\"done\"><span class=\"icon\">✓</span><div class=\"title\">Everything is already up to date.</div></li>";

  $("error").hidden = !job.error;
  $("error").textContent = job.error || "";
  $("warnings").innerHTML = job.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join("");
  const ok = job.finished && !job.error;
  $("retry").hidden = !job.error;
  $("change").hidden = !job.error;
  $("open").hidden = !(ok && status.ready);
  $("back2").hidden = !(job.running && status.ready);
  $("run-lead").textContent = ok ? "All set. GravelMaps now works offline for these states."
    : job.error ? "Setup stopped. Nothing is lost: trying again picks up where it left off."
      : "Setting up GravelMaps. Keep this window open; it's fine to keep using your computer.";
  if (ok && status.ready) {
    clearInterval(poller);
    poller = null;
  }
}

async function poll() {
  try {
    const status = await api("/api/setup/status");
    if (status.job) renderRun(status);
  } catch {
    $("run-lead").textContent = "Lost contact with GravelMaps. Is it still running?";
  }
}

function follow() {
  if (!poller) poller = setInterval(poll, 1000);
  poll();
}

async function start(req) {
  lastRequest = req;
  try {
    renderRun({ ready: false, job: await api("/api/setup", req) });
    follow();
  } catch (err) {
    alertBox(err.message);
  }
}

function alertBox(msg) {
  $("chosen").textContent = msg;
}

(async function init() {
  const [list, status] = await Promise.all([api("/api/setup/states"), api("/api/setup/status")]);
  states = list;
  status.codes.forEach((c) => chosen.add(c));
  $("filter").addEventListener("input", renderStates);
  $("start").addEventListener("click", () => start({ states: [...chosen] }));
  $("update").addEventListener("click", () => start({ states: status.codes, update_data: true }));
  $("finish").addEventListener("click", () => start({ states: status.codes }));
  $("retry").addEventListener("click", () => start(lastRequest || { states: [...chosen] }));
  $("change").addEventListener("click", () => showPick(status));
  for (const id of ["back", "back2", "open"]) $(id).addEventListener("click", () => { location.href = "/"; });

  const job = status.job;
  if (job && (job.running || job.error)) {
    lastRequest = { states: status.codes };
    renderRun(status);
    if (job.running) follow();
  } else {
    showPick(status);
  }
})();
