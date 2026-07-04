"use strict";
const $ = (id) => document.getElementById(id);
const S = { pid: null, proj: null, busy: false, sel: null, effects: [], pps: 40 };

function toast(m, ms) { const t = $("toast"); t.textContent = m; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms || 2800); }
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function tc(sec) { sec = Math.max(0, sec || 0); const f = Math.round((sec % 1) * 30); const s = Math.floor(sec) % 60, m = Math.floor(sec / 60) % 60, h = Math.floor(sec / 3600); const p = (n) => String(n).padStart(2, "0"); return `${p(h)}:${p(m)}:${p(s)}:${p(f)}`; }

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
async function tool(name, args) {
  return api("/api/tool", { method: "POST", body: JSON.stringify({ name, args: Object.assign({ project_id: S.pid }, args || {}) }) });
}

// ---------------------------------------------------------------- projects
async function loadProjects(selectId) {
  const { projects } = await api("/api/tool", { method: "POST", body: JSON.stringify({ name: "get_projects", args: {} }) });
  const sel = $("projectSelect");
  sel.innerHTML = projects.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("") || "<option value=''>— no projects —</option>";
  if (selectId) sel.value = selectId;
  S.pid = sel.value || null;
  if (S.pid) await refresh();
}

async function refresh() {
  if (!S.pid) return;
  const { project, duration } = await tool("get_timeline");
  S.proj = project;
  const mediaUrl = (f) => `/api/projects/${S.pid}/media/${f}`;

  // media grid
  const q = ($("mediaSearch").value || "").toLowerCase();
  const media = project.media.filter(m => !q || m.name.toLowerCase().includes(q));
  $("itemCount").textContent = project.media.length + " item" + (project.media.length === 1 ? "" : "s");
  $("mediaGrid").innerHTML = media.map(m => {
    const ph = m.kind === "audio" ? "🎵" : m.kind === "image" ? "🖼" : "🎬";
    const thumb = m.thumb ? `<img src="${mediaUrl(m.thumb)}" alt="" loading="lazy">` : `<span class="ph">${ph}</span>`;
    const badge = m.duration ? `<span class="badge">${tc(m.duration).slice(3)}</span>` : "";
    return `<div class="mcard" data-mid="${m.id}" title="Click to add to timeline"><div class="thumb">${thumb}${badge}</div><div class="mname">${esc(m.name)}</div></div>`;
  }).join("") || '<div class="media-none">No media yet — click <b>⬆ Import</b>.</div>';

  // timeline tracks
  const total = Math.max(0.001, duration);
  $("tlDur").textContent = duration.toFixed(1) + "s";
  $("tcTotal").textContent = tc(duration);
  const clipHTML = (c, i, audio) => {
    const m = project.media.find(x => x.id === c.media_id) || { name: "?" };
    const w = Math.max(44, (c.out - c.in) * S.pps);
    const fx = (c.effects && c.effects.length) ? `<span class="fx" title="${c.effects.join(', ')}">✨${c.effects.length}</span>` : "";
    return `<div class="clip ${audio ? 'aclip' : ''} ${S.sel === c.id && !audio ? 'sel' : ''}" style="width:${w}px" data-cid="${c.id}" title="${esc(m.name)}  ${c.in.toFixed(1)}–${c.out.toFixed(1)}s">
      <div class="cn">${esc(m.name)}</div><div class="ct">${(c.out - c.in).toFixed(1)}s</div>${audio ? '' : fx}
      ${audio ? '' : `<div class="cacts"><button data-act="left" data-cid="${c.id}" data-i="${i}">◀</button><button data-act="split" data-cid="${c.id}">✂</button><button data-act="del" data-cid="${c.id}">✕</button><button data-act="right" data-cid="${c.id}" data-i="${i}">▶</button></div>`}
    </div>`;
  };
  $("laneV1").innerHTML = project.clips.map((c, i) => clipHTML(c, i, false)).join("") || '<span class="lane-none">Empty — click media above to add clips.</span>';
  const audioClips = project.clips.map((c, i) => { const m = project.media.find(x => x.id === c.media_id); return (m && m.has_audio) ? clipHTML(c, i, true) : ""; }).join("");
  $("laneA1").innerHTML = audioClips;
  $("laneA2").innerHTML = "";

  // ruler
  const laneW = total * S.pps + 20;
  let ruler = "";
  const step = total > 60 ? 10 : total > 20 ? 5 : 2;
  for (let t = 0; t <= total; t += step) ruler += `<span class="tick" style="left:${42 + t * S.pps}px">${tc(t).slice(3)}</span>`;
  $("ruler").innerHTML = ruler;

  // inspector
  const ar = gcdRatio(project.width, project.height);
  $("inspector").innerHTML = `
    <div class="insp-group">Project</div>
    <div class="insp-row"><span class="k">Name</span><span class="v">${esc(project.name)}</span></div>
    <div class="insp-row"><span class="k">Path</span><span class="v mono" style="font-size:10px">…/${project.id}</span></div>
    <div class="insp-group">Format</div>
    <div class="insp-row"><span class="k">Resolution</span><span class="v">${project.width} × ${project.height}</span></div>
    <div class="insp-row"><span class="k">Frame Rate</span><span class="v">${project.fps} fps</span></div>
    <div class="insp-row"><span class="k">Aspect Ratio</span><span class="v">${ar}</span></div>
    <div class="insp-row"><span class="k">Duration</span><span class="v mono">${tc(duration)}</span></div>
    <div class="insp-group">Timeline</div>
    <div class="insp-row"><span class="k">Clips</span><span class="v">${project.clips.length}</span></div>
    <div class="insp-row"><span class="k">Media</span><span class="v">${project.media.length}</span></div>
    <div class="insp-row"><span class="k">Overlays</span><span class="v">${project.texts.length}</span></div>`;
}
function gcdRatio(w, h) { const g = (a, b) => b ? g(b, a % b) : a; const d = g(w, h) || 1; return `${w / d}:${h / d}`; }

// ---------------------------------------------------------------- clicks (delegation)
document.addEventListener("click", async (e) => {
  const fxbtn = e.target.closest(".fx-grid button");
  if (fxbtn) { await toggleEffect(fxbtn.dataset.fx); return; }
  if (!e.target.closest(".fx-pop") && !e.target.closest(".clip")) closeFxPop();
  const b = e.target.closest("[data-act],.mcard,.ag-suggest,.clip");
  if (!b) return;
  try {
    if (b.classList.contains("mcard")) {
      const m = S.proj.media.find(x => x.id === b.dataset.mid);
      await tool("add_clips", { clips: [{ media_id: m.id, in: 0, out: m.duration || 3 }] });
      await refresh(); return;
    }
    if (b.classList.contains("ag-suggest")) { $("agentInput").value = b.dataset.q; sendAgent(); return; }
    if (b.dataset.act) {
      const cid = b.dataset.cid, act = b.dataset.act;
      if (act === "del") await tool("delete_clip", { clip_id: cid });
      else if (act === "split") { const c = S.proj.clips.find(x => x.id === cid); await tool("split_clip", { clip_id: cid, at: (c.in + c.out) / 2 }); }
      else { const i = parseInt(b.dataset.i, 10); await tool("move_clip", { clip_id: cid, index: act === "left" ? Math.max(0, i - 1) : i + 1 }); }
      await refresh(); return;
    }
    if (b.classList.contains("clip") && !b.classList.contains("aclip")) { S.sel = b.dataset.cid; openFxPop(b); await refresh(); }
  } catch (err) { toast("Error: " + err.message, 4000); }
});

// ---------------------------------------------------------------- effects popover
async function openFxPop(clipEl) {
  closeFxPop();
  if (!S.effects.length) { try { S.effects = (await tool("list_effects")).effects; } catch { S.effects = []; } }
  const clip = S.proj.clips.find(c => c.id === S.sel); const on = new Set((clip && clip.effects) || []);
  const pop = document.createElement("div"); pop.className = "fx-pop"; pop.id = "fxPop";
  pop.innerHTML = `<h4>✨ Effects — click to toggle</h4><div class="fx-grid">` +
    S.effects.map(fx => `<button data-fx="${fx}" class="${on.has(fx) ? 'on' : ''}">${fx}</button>`).join("") + `</div>`;
  document.body.appendChild(pop);
  const r = clipEl.getBoundingClientRect();
  pop.style.left = Math.min(window.innerWidth - 260, Math.max(8, r.left)) + "px";
  pop.style.top = Math.max(8, r.top - pop.offsetHeight - 8) + "px";
}
function closeFxPop() { const p = $("fxPop"); if (p) p.remove(); }
async function toggleEffect(fx) {
  const clip = S.proj.clips.find(c => c.id === S.sel); if (!clip) return;
  const has = (clip.effects || []).includes(fx);
  await tool(has ? "remove_effect" : "apply_effect", { clip_id: S.sel, effect: fx });
  await refresh();
  const el = document.querySelector(`.clip[data-cid="${S.sel}"]`); if (el) openFxPop(el);
  toast((has ? "Removed " : "Applied ") + fx);
}

// ---------------------------------------------------------------- upload / export / theme
$("fileInput").addEventListener("change", async (e) => {
  if (!S.pid) { toast("Create a project first"); return; }
  for (const f of e.target.files) {
    const fd = new FormData(); fd.append("file", f);
    toast("Importing " + f.name + "…", 12000);
    const r = await fetch(`/api/projects/${S.pid}/upload`, { method: "POST", body: fd });
    if (!r.ok) toast("Import failed: " + f.name, 4000);
  }
  e.target.value = ""; await refresh(); toast("Imported ✓");
});
$("exportBtn").onclick = async () => {
  if (!S.pid || S.busy) return;
  S.busy = true; const t = $("exportBtn").textContent; $("exportBtn").textContent = "Rendering…"; $("exportBtn").disabled = true;
  try {
    const { url } = await tool("export_project");
    $("previewEmpty").hidden = true;
    const v = $("player"); v.src = url + "?t=" + Date.now(); v.hidden = false; v.play().catch(() => {});
    v.onloadedmetadata = () => { $("timecode").firstChild.textContent = "00:00:00:00 "; };
    v.ontimeupdate = () => { $("timecode").firstChild.textContent = tc(v.currentTime) + " "; };
    toast("Render complete ✓");
  } catch (err) { toast("Render failed: " + err.message, 6000); }
  S.busy = false; $("exportBtn").textContent = t; $("exportBtn").disabled = false;
};
$("themeToggle").onclick = () => {
  const html = document.documentElement, dark = html.getAttribute("data-theme") !== "light";
  html.setAttribute("data-theme", dark ? "light" : "dark");
  $("themeToggle").textContent = dark ? "☀" : "☾";
  localStorage.setItem("sm_theme", dark ? "light" : "dark");
};
$("mediaSearch").addEventListener("input", () => refresh());
$("zoom").addEventListener("input", (e) => { S.pps = e.target.value / 3; refresh(); });

// project switching
$("projectSelect").onchange = () => { S.pid = $("projectSelect").value; S.sel = null; refresh(); };
$("newProject").onclick = async () => {
  const name = prompt("Project name:", "Aesthetic video") || ""; if (!name.trim()) return;
  const { project } = await api("/api/tool", { method: "POST", body: JSON.stringify({ name: "create_project", args: { name: name.trim() } }) });
  await loadProjects(project.id);
};
$("generateBtn").onclick = () => { $("agentInput").value = "Generate a title card"; toast("Ask the agent to generate — e.g. add a title overlay"); $("agentInput").focus(); };
$("newFolderBtn").onclick = () => toast("Folders coming soon — everything lives in the project for now");

// ---------------------------------------------------------------- agent
function agLine(cls, html) { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; $("agentLog").appendChild(d); $("agentLog").scrollTop = 1e9; return d; }
let _agentAbort = null;
function _agentBtn(busy) {
  const b = $("agentSend");
  b.textContent = busy ? "■" : "↑";
  b.title = busy ? "Stop" : "Send";
  b.style.fontSize = busy ? "18px" : "";
}
async function sendAgent() {
  const q = $("agentInput").value.trim();
  if (!q || S.agentBusy) return;
  $("agentInput").value = ""; S.agentBusy = true; agLine("ag-user", esc(q));
  _agentAbort = new AbortController();
  _agentBtn(true);
  const sel = $("modelSelect").value;
  try {
    const r = await fetch("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: q, project_id: S.pid, agent_model: sel, model: sel }), signal: _agentAbort.signal });
    if (!r.ok || !r.body) throw new Error(await r.text());
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) {
      const { done, value } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1); if (!line) continue;
        let ev; try { ev = JSON.parse(line); } catch { continue; }
        if (ev.type === "tool") agLine("ag-tool", `⚙ <b>${esc(ev.name)}</b> <span>${esc(JSON.stringify(ev.args)).slice(0, 90)}</span>`);
        else if (ev.type === "tool_result") { await refresh(); if (ev.name === "export_project" && ev.result.includes("/renders/")) { try { const u = JSON.parse(ev.result).url; $("previewEmpty").hidden = true; $("player").hidden = false; $("player").src = u + "?t=" + Date.now(); } catch {} } }
        else if (ev.type === "final") agLine("ag-final", esc(ev.text));
        else if (ev.type === "error") agLine("ag-err", esc(ev.text));
      }
    }
  } catch (err) {
    if (err.name === "AbortError") agLine("ag-final", "⏹ Stopped by user.");
    else agLine("ag-err", esc(err.message));
  }
  S.agentBusy = false; _agentAbort = null; _agentBtn(false);
}
$("agentSend").onclick = () => { if (S.agentBusy && _agentAbort) { _agentAbort.abort(); } else { sendAgent(); } };
$("agentInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!S.agentBusy) sendAgent(); } });

// ---------------------------------------------------------------- boot
(async function boot() {
  const saved = localStorage.getItem("sm_theme"); if (saved === "light") { document.documentElement.setAttribute("data-theme", "light"); $("themeToggle").textContent = "☀"; }
  try {
    const h = await api("/api/health");
    if (!h.ffmpeg) toast("⚠ ffmpeg not found — rendering won't work", 6000);
    $("agentModel").textContent = h.llm ? "· Ollama ✓" : "· Ollama offline";
    await loadProjects();
    if (!S.pid) { const { project } = await api("/api/tool", { method: "POST", body: JSON.stringify({ name: "create_project", args: { name: "Aesthetic video" } }) }); await loadProjects(project.id); }
  } catch (e) { toast("Backend offline: " + e.message, 6000); }
})();
