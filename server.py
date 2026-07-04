"""Source Montage — the video editor built for AIs (Windows).

Modeled on Palmier Pro's architecture: a timeline video editor whose first-class user is
an AI agent. Exposes a real MCP server over HTTP (JSON-RPC: initialize / tools/list /
tools/call) so Claude Code, Cursor, or any MCP client can edit the timeline — plus a REST
API for the bundled UI and an in-app agent driven by local Ollama. Rendering is ffmpeg.

    claude mcp add --transport http source-montage http://127.0.0.1:19790/mcp
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

APP_NAME = "Source Montage"
DATA_DIR = Path(os.getenv("SOURCE_MONTAGE_DATA") or (Path(os.getenv("LOCALAPPDATA") or Path.home()) / "SourceMontage"))
PROJECTS_DIR = DATA_DIR / "projects"
for d in (DATA_DIR, PROJECTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

STATIC_DIR = (Path(sys._MEIPASS) / "static" if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parent.parent / "static")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
FFMPEG = os.getenv("FFMPEG", "ffmpeg")
FFPROBE = os.getenv("FFPROBE", "ffprobe")

# --------------------------------------------------------------------------- AI generation API keys
REPLICATE_API_TOKEN = "r8_5fLPZpQawKrQJB9XwTA7dQLQ0NEO7oS4XVQNL"
MINIMAX_API_KEY = "sk-api-b8A4iNVqQFaS3UQcp7xq8lnAl4rP8BVrxxbeYiBTVjIcoEougFkFugS3OzpJDkApeOPfDYbwK6HQXtPcevlYssv-x_XLttE3TONwg6UvHTqGSyCCsYilzDU"
POLLINATIONS_KEY = "sk_TCVQvXEzEBE5znEy3WIgLI00kuvBtP8s"

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------------- project store
def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "project").strip()).strip("-").lower() or "project"


def _proj_path(pid: str) -> Path:
    return PROJECTS_DIR / pid / "project.json"


def _media_dir(pid: str) -> Path:
    d = PROJECTS_DIR / pid / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _renders_dir(pid: str) -> Path:
    d = PROJECTS_DIR / pid / "renders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_project(pid: str) -> dict:
    p = _proj_path(pid)
    if not p.exists():
        raise HTTPException(404, f"project '{pid}' not found")
    return json.loads(p.read_text(encoding="utf-8"))


def save_project(proj: dict) -> None:
    proj["updated"] = time.time()
    _proj_path(proj["id"]).write_text(json.dumps(proj, indent=1), encoding="utf-8")


def new_project(name: str) -> dict:
    pid = _slug(name) + "-" + uuid.uuid4().hex[:6]
    (PROJECTS_DIR / pid).mkdir(parents=True, exist_ok=True)
    proj = {"id": pid, "name": name or pid, "created": time.time(), "updated": time.time(),
            "fps": 30, "width": 1920, "height": 1080,
            "media": [],      # {id,name,path,kind,duration,width,height}
            "clips": [],      # ordered video track: {id,media_id,in,out}  (seconds within source)
            "texts": [],      # overlays: {id,content,start,end,x,y,size,color}
            "renders": []}    # {id,file,created,status}
    save_project(proj)
    return proj


def list_projects() -> list[dict]:
    out = []
    for d in PROJECTS_DIR.iterdir():
        p = d / "project.json"
        if p.exists():
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": j["id"], "name": j["name"], "updated": j.get("updated", 0),
                            "clips": len(j.get("clips", [])), "media": len(j.get("media", []))})
            except Exception:
                continue
    out.sort(key=lambda x: -x["updated"])
    return out


# --------------------------------------------------------------------------- media probing
def probe(path: Path) -> dict:
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                            "-show_streams", str(path)], capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout or "{}")
        dur = float((j.get("format") or {}).get("duration") or 0)
        v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
        a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
        kind = "video" if v and dur else ("audio" if a else ("image" if v else "other"))
        if v and not dur:
            kind = "image"
        return {"duration": round(dur, 3), "width": (v or {}).get("width"), "height": (v or {}).get("height"),
                "kind": kind, "has_audio": bool(a)}
    except Exception:
        return {"duration": 0, "width": None, "height": None, "kind": "other", "has_audio": False}


def import_media_file(proj: dict, src: Path, name: str | None = None) -> dict:
    if not src.exists() or not src.is_file():
        raise HTTPException(400, f"file not found: {src}")
    mid = "m" + uuid.uuid4().hex[:8]
    dest = _media_dir(proj["id"]) / (mid + src.suffix.lower())
    shutil.copy2(src, dest)
    info = probe(dest)
    thumb = _make_thumb(proj["id"], mid, dest, info.get("kind"))
    item = {"id": mid, "name": name or src.name, "path": dest.name, "thumb": thumb, **info}
    proj["media"].append(item)
    save_project(proj)
    return item


def _make_thumb(pid: str, mid: str, src: Path, kind: str | None) -> str | None:
    """First-frame jpg thumbnail for the media grid."""
    out = _media_dir(pid) / (mid + "_thumb.jpg")
    try:
        if kind in ("video", "image"):
            args = [FFMPEG, "-y"]
            if kind == "video":
                args += ["-ss", "0.5"]
            args += ["-i", str(src), "-frames:v", "1", "-vf", "scale=320:-1", str(out)]
            r = subprocess.run(args, capture_output=True, timeout=30)
            if out.exists():
                return out.name
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- render engine (ffmpeg)
def _clip_media(proj: dict, media_id: str) -> dict:
    m = next((m for m in proj["media"] if m["id"] == media_id), None)
    if not m:
        raise HTTPException(400, f"media '{media_id}' not in project")
    return m


def timeline_duration(proj: dict) -> float:
    return round(sum(max(0.0, c["out"] - c["in"]) for c in proj["clips"]), 3)


def _ff_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _font_file() -> str | None:
    """drawtext on Windows needs an explicit fontfile (no fontconfig default)."""
    fonts = Path(os.getenv("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("segoeui.ttf", "arialbd.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf"):
        f = fonts / name
        if f.exists():
            # filter syntax wants forward slashes + escaped drive colon
            return str(f).replace("\\", "/").replace(":", "\\:")
    return None


# Special effects — real-editor filters. Value is an ffmpeg video-filter fragment.
EFFECTS = {
    "grayscale":  "hue=s=0",
    "sepia":      "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "vintage":    "curves=preset=vintage",
    "blur":       "gblur=sigma=7",
    "sharpen":    "unsharp=5:5:1.0:5:5:0.0",
    "vignette":   "vignette=PI/4",
    "brighten":   "eq=brightness=0.12",
    "darken":     "eq=brightness=-0.12",
    "contrast":   "eq=contrast=1.35",
    "saturate":   "eq=saturation=1.6",
    "desaturate": "eq=saturation=0.45",
    "warm":       "colorbalance=rs=.12:gs=.02:bs=-.10",
    "cool":       "colorbalance=rs=-.10:gs=0:bs=.14",
    "mirror":     "hflip",
    "invert":     "negate",
    "cinematic":  "curves=preset=medium_contrast,eq=saturation=1.15,vignette=PI/5",
    "kenburns":   "zoompan=z='min(zoom+0.0009,1.20)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "glow":       "gblur=sigma=9[bg];[fx][bg]blend=all_mode=screen:all_opacity=0.45",  # handled specially
}
EFFECT_LIST = [k for k in EFFECTS if k != "glow"] + ["glow", "fadein", "fadeout"]


def _clip_video_chain(i: int, dur: float, base: str, effects: list) -> str:
    """base = the pre-effect filter string ending WITHOUT the output label. Returns
    '[i:v]<base>,<effects...>[vI];' with fade/glow handled specially."""
    parts = [base]
    for e in (effects or []):
        if e == "fadein":
            parts.append("fade=t=in:st=0:d=0.6")
        elif e == "fadeout":
            parts.append(f"fade=t=out:st={max(0.0, dur - 0.6):.3f}:d=0.6")
        elif e == "glow":
            # split → blur one copy → screen-blend back
            body = ",".join(parts)
            return (f"[{i}:v]{body},split[fx][gb];[gb]gblur=sigma=9[gbb];"
                    f"[fx][gbb]blend=all_mode=screen:all_opacity=0.5[v{i}];")
        elif e in EFFECTS:
            parts.append(EFFECTS[e])
    return f"[{i}:v]{','.join(parts)}[v{i}];"


def render_project(proj: dict) -> dict:
    """Flatten the clip sequence + effects + text overlays into an mp4 via one ffmpeg run."""
    if not proj["clips"]:
        raise HTTPException(400, "timeline is empty — add clips first")
    W, H, FPS = proj["width"], proj["height"], proj["fps"]
    inputs, vparts, aparts = [], [], []
    for i, c in enumerate(proj["clips"]):
        m = _clip_media(proj, c["media_id"])
        f = _media_dir(proj["id"]) / m["path"]
        dur = max(0.1, c["out"] - c["in"])
        effects = c.get("effects", [])
        pad = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}"
        if m["kind"] == "image":
            inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(f)]
            vparts.append(_clip_video_chain(i, dur, pad, effects))
            aparts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}[a{i}];")
        else:
            inputs += ["-i", str(f)]
            base = f"trim={c['in']:.3f}:{c['out']:.3f},setpts=PTS-STARTPTS,{pad}"
            vparts.append(_clip_video_chain(i, dur, base, effects))
            if m.get("has_audio"):
                aparts.append(f"[{i}:a]atrim={c['in']:.3f}:{c['out']:.3f},asetpts=PTS-STARTPTS,"
                              f"aresample=48000,aformat=channel_layouts=stereo[a{i}];")
            else:
                aparts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}[a{i}];")
    n = len(proj["clips"])
    fc = "".join(vparts) + "".join(aparts)
    fc += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];"
    # text overlays over the flattened timeline
    vin = "[vc]"
    font = _font_file()
    for t_i, t in enumerate(proj["texts"]):
        out = f"[vt{t_i}]"
        fc += (f"{vin}drawtext=text='{_ff_escape(t['content'])}'"
               + (f":fontfile='{font}'" if font else "")
               + f":fontcolor={t.get('color', 'white')}:fontsize={int(t.get('size', 64))}"
               f":x=(w-text_w)*{float(t.get('x', 0.5)):.3f}:y=(h-text_h)*{float(t.get('y', 0.85)):.3f}"
               f":borderw=3:bordercolor=black@0.7"
               f":enable='between(t,{t['start']:.3f},{t['end']:.3f})'{out};")
        vin = out
    vmap = vin.strip("[]")
    rid = "r" + uuid.uuid4().hex[:8]
    outfile = _renders_dir(proj["id"]) / f"{rid}.mp4"
    cmd = [FFMPEG, "-y", *inputs, "-filter_complex", fc, "-map", f"[{vmap}]", "-map", "[ac]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest", str(outfile)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not outfile.exists():
        raise HTTPException(500, "render failed: " + (r.stderr or "")[-800:])
    rec = {"id": rid, "file": outfile.name, "created": time.time(),
           "duration": timeline_duration(proj), "size": outfile.stat().st_size}
    proj["renders"].append(rec)
    save_project(proj)
    return rec


# --------------------------------------------------------------------------- tool executor (shared by MCP + agent + REST)
def exec_tool(name: str, args: dict) -> dict:
    args = args or {}

    if name == "get_projects":
        return {"projects": list_projects()}
    if name == "create_project":
        return {"project": new_project(str(args.get("name", "Untitled")))}
    if name == "list_effects":
        return {"effects": EFFECT_LIST}

    pid = str(args.get("project_id", ""))
    if not pid:
        pl = list_projects()
        if len(pl) == 1:
            pid = pl[0]["id"]
        else:
            raise HTTPException(400, "project_id required (call get_projects)")
    proj = load_project(pid)

    if name == "get_timeline":
        return {"project": {k: proj[k] for k in ("id", "name", "fps", "width", "height", "media", "clips", "texts")},
                "duration": timeline_duration(proj)}
    if name == "get_media":
        return {"media": proj["media"]}
    if name == "import_media":
        return {"media": import_media_file(proj, Path(str(args.get("path", ""))))}
    if name == "add_clips":
        added = []
        for c in (args.get("clips") or []):
            m = _clip_media(proj, str(c.get("media_id")))
            cin = float(c.get("in", 0))
            cout = float(c.get("out", m["duration"] or cin + 3))
            if cout <= cin:
                raise HTTPException(400, "clip out must be > in")
            clip = {"id": "c" + uuid.uuid4().hex[:8], "media_id": m["id"], "in": cin, "out": cout,
                    "effects": [e for e in (c.get("effects") or []) if e in EFFECT_LIST]}
            idx = c.get("index")
            if idx is None:
                proj["clips"].append(clip)
            else:
                proj["clips"].insert(max(0, min(int(idx), len(proj["clips"]))), clip)
            added.append(clip)
        save_project(proj)
        return {"added": added, "duration": timeline_duration(proj)}
    if name in ("apply_effect", "remove_effect"):
        cid = str(args.get("clip_id"))
        clip = next((c for c in proj["clips"] if c["id"] == cid), None)
        if not clip:
            raise HTTPException(404, "clip not found")
        clip.setdefault("effects", [])
        eff = str(args.get("effect", "")).lower().strip()
        if eff not in EFFECT_LIST:
            raise HTTPException(400, f"unknown effect '{eff}'. Available: {', '.join(EFFECT_LIST)}")
        if name == "apply_effect":
            if eff not in clip["effects"]:
                clip["effects"].append(eff)
        else:
            clip["effects"] = [e for e in clip["effects"] if e != eff]
        save_project(proj)
        return {"clip": clip}
    if name == "move_clip":
        cid = str(args.get("clip_id")); idx = int(args.get("index", 0))
        clip = next((c for c in proj["clips"] if c["id"] == cid), None)
        if not clip:
            raise HTTPException(404, "clip not found")
        proj["clips"].remove(clip)
        proj["clips"].insert(max(0, min(idx, len(proj["clips"]))), clip)
        save_project(proj)
        return {"clips": proj["clips"]}
    if name == "trim_clip":
        cid = str(args.get("clip_id"))
        clip = next((c for c in proj["clips"] if c["id"] == cid), None)
        if not clip:
            raise HTTPException(404, "clip not found")
        if "in" in args:
            clip["in"] = float(args["in"])
        if "out" in args:
            clip["out"] = float(args["out"])
        if clip["out"] <= clip["in"]:
            raise HTTPException(400, "out must be > in")
        save_project(proj)
        return {"clip": clip, "duration": timeline_duration(proj)}
    if name == "split_clip":
        cid = str(args.get("clip_id")); at = float(args.get("at", 0))
        clip = next((c for c in proj["clips"] if c["id"] == cid), None)
        if not clip or not (clip["in"] < at < clip["out"]):
            raise HTTPException(400, "split point must fall inside the clip's in/out")
        second = {"id": "c" + uuid.uuid4().hex[:8], "media_id": clip["media_id"], "in": at, "out": clip["out"]}
        clip["out"] = at
        proj["clips"].insert(proj["clips"].index(clip) + 1, second)
        save_project(proj)
        return {"clips": proj["clips"]}
    if name == "delete_clip":
        cid = str(args.get("clip_id"))
        proj["clips"] = [c for c in proj["clips"] if c["id"] != cid]
        save_project(proj)
        return {"clips": proj["clips"], "duration": timeline_duration(proj)}
    if name == "add_texts":
        added = []
        for t in (args.get("texts") or []):
            item = {"id": "t" + uuid.uuid4().hex[:8], "content": str(t.get("content", "")),
                    "start": float(t.get("start", 0)), "end": float(t.get("end", 3)),
                    "x": float(t.get("x", 0.5)), "y": float(t.get("y", 0.85)),
                    "size": int(t.get("size", 64)), "color": str(t.get("color", "white"))}
            proj["texts"].append(item)
            added.append(item)
        save_project(proj)
        return {"added": added}
    if name == "delete_text":
        tid = str(args.get("text_id"))
        proj["texts"] = [t for t in proj["texts"] if t["id"] != tid]
        save_project(proj)
        return {"texts": proj["texts"]}
    if name == "export_project":
        rec = render_project(proj)
        return {"render": rec, "url": f"/api/projects/{proj['id']}/renders/{rec['file']}"}
    raise HTTPException(400, f"unknown tool: {name}")


TOOLS = [
    {"name": "get_projects", "description": "List all Source Montage projects.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "create_project", "description": "Create a new video project.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "get_timeline", "description": "Full project state: media library, clip sequence, text overlays, duration.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}}},
    {"name": "get_media", "description": "List the project's imported media.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}}},
    {"name": "import_media", "description": "Import a video/image/audio file from an absolute path on this machine.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "path": {"type": "string"}}, "required": ["path"]}},
    {"name": "add_clips", "description": "Append clips to the timeline. Each clip: {media_id, in, out, index?} (seconds in the source).",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clips": {"type": "array"}}, "required": ["clips"]}},
    {"name": "trim_clip", "description": "Change a clip's in/out points.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}, "in": {"type": "number"}, "out": {"type": "number"}}, "required": ["clip_id"]}},
    {"name": "split_clip", "description": "Split a clip at a source-time point (seconds).",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}, "at": {"type": "number"}}, "required": ["clip_id", "at"]}},
    {"name": "move_clip", "description": "Reorder a clip to a new index in the sequence.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}, "index": {"type": "integer"}}, "required": ["clip_id", "index"]}},
    {"name": "delete_clip", "description": "Remove a clip from the timeline.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}}, "required": ["clip_id"]}},
    {"name": "add_texts", "description": "Add text overlays: {content, start, end, x(0-1), y(0-1), size, color}.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "texts": {"type": "array"}}, "required": ["texts"]}},
    {"name": "delete_text", "description": "Remove a text overlay.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "text_id": {"type": "string"}}, "required": ["text_id"]}},
    {"name": "list_effects", "description": "List the available special video effects (color grades, blur, vignette, cinematic, glow, fades, etc.).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "apply_effect", "description": "Apply a special video effect to a clip (grayscale, sepia, vintage, cinematic, blur, sharpen, vignette, glow, warm, cool, brighten, darken, contrast, saturate, mirror, invert, kenburns, fadein, fadeout).",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}, "effect": {"type": "string"}}, "required": ["clip_id", "effect"]}},
    {"name": "remove_effect", "description": "Remove an effect from a clip.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "clip_id": {"type": "string"}, "effect": {"type": "string"}}, "required": ["clip_id", "effect"]}},
    {"name": "export_project", "description": "Render the timeline to an mp4 (ffmpeg). Returns the render record + download URL.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}}},
]


# --------------------------------------------------------------------------- MCP server (HTTP JSON-RPC)
@app.post("/mcp")
async def mcp(request: Request):
    """Streamable-HTTP MCP endpoint: initialize / tools/list / tools/call."""
    try:
        msg = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON-RPC")
    mid = msg.get("id")
    method = msg.get("method", "")

    def rpc(result=None, error=None):
        body = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            body["error"] = error
        else:
            body["result"] = result
        return JSONResponse(body)

    if method == "initialize":
        return rpc({"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "source-montage", "version": "0.1.0"}})
    if method in ("notifications/initialized", "initialized"):
        return JSONResponse({}, status_code=202)
    if method == "tools/list":
        return rpc({"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params", {}) or {}
        try:
            out = exec_tool(params.get("name", ""), params.get("arguments") or {})
            return rpc({"content": [{"type": "text", "text": json.dumps(out)}], "isError": False})
        except HTTPException as e:
            return rpc({"content": [{"type": "text", "text": f"error: {e.detail}"}], "isError": True})
        except Exception as e:
            return rpc({"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    if method == "ping":
        return rpc({})
    return rpc(error={"code": -32601, "message": f"method not found: {method}"})


# --------------------------------------------------------------------------- REST for the UI
class ToolIn(BaseModel):
    name: str
    args: dict | None = None


@app.get("/api/ping")
def ping():
    return {"ok": True}


@app.get("/api/health")
def health():
    ff = shutil.which(FFMPEG) is not None
    try:
        llm = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0).status_code == 200
    except Exception:
        llm = False
    return {"ok": True, "ffmpeg": ff, "llm": llm, "projects": len(list_projects()),
            "mcp": "http://127.0.0.1:19790/mcp"}


@app.post("/api/tool")
def api_tool(body: ToolIn):
    return exec_tool(body.name, body.args or {})


@app.post("/api/projects/{pid}/upload")
async def upload_media(pid: str, file: UploadFile = File(...)):
    proj = load_project(pid)
    tmp = _media_dir(pid) / ("upload_" + re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "file"))
    tmp.write_bytes(await file.read())
    item = import_media_file(proj, tmp, name=file.filename)
    tmp.unlink(missing_ok=True)
    return {"media": item}


@app.get("/api/projects/{pid}/media/{fname}")
def get_media_file(pid: str, fname: str):
    f = _media_dir(pid) / Path(fname).name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.get("/api/projects/{pid}/renders/{fname}")
def get_render_file(pid: str, fname: str):
    f = _renders_dir(pid) / Path(fname).name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="video/mp4")


# --------------------------------------------------------------------------- AI media generation (Source Gen 1.0)
import urllib.parse as _urlparse
import random as _random


def _parse_gen_request(prompt: str):
    """Extract media_type and aspect ratio from a user prompt."""
    low = prompt.lower()
    # detect video vs image
    video_kw = ("video", "animation", "motion", "moving", "gif", "mp4", "clip", "animate", "cinematic shot")
    media_type = "video" if any(w in low for w in video_kw) else "image"
    # detect aspect ratio
    if any(k in low for k in ("9:16", "vertical", "portrait", "mobile")):
        w, h = 720, 1280
    elif any(k in low for k in ("1:1", "square")):
        w, h = 1024, 1024
    else:  # default widescreen 16:9
        w, h = 1280, 720
    return media_type, w, h


def _gen_image_minimax(prompt: str, width: int, height: int) -> Path | None:
    """Generate an image via MiniMax API. Returns the saved file path or None."""
    try:
        r = httpx.post(
            "https://api.minimax.io/v1/image_generation",
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={"prompt": prompt, "model": "image-01", "width": width, "height": height, "n": 1,
                  "response_format": "url"},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        # MiniMax returns {"data": [{"url": "..."}]}
        url = None
        if "data" in data and data["data"]:
            url = data["data"][0].get("url")
        if not url:
            return None
        img_bytes = httpx.get(url, timeout=60.0).content
        fname = f"generated_image_{int(time.time())}.jpg"
        out = DATA_DIR / fname
        out.write_bytes(img_bytes)
        return out
    except Exception:
        return None


def _gen_image_pollinations(prompt: str, width: int, height: int) -> Path | None:
    """Fallback: generate an image via Pollinations.ai. Returns file path or None."""
    try:
        safe_prompt = _urlparse.quote(prompt.strip())
        seed = _random.randint(1000, 99999)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}&seed={seed}&nologo=true"
        headers = {"Authorization": f"Bearer {POLLINATIONS_KEY}"}
        r = httpx.get(url, headers=headers, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        fname = f"generated_image_{int(time.time())}.jpg"
        out = DATA_DIR / fname
        out.write_bytes(r.content)
        return out
    except Exception:
        return None


def _gen_video_minimax(prompt: str, width: int = 1280, height: int = 720) -> Path | None:
    """Generate a video via MiniMax API (async task). Returns saved MP4 path or None."""
    try:
        r = httpx.post(
            "https://api.minimax.io/v1/video_generation",
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={"prompt": prompt, "model": "video-01"},
            timeout=30.0,
        )
        r.raise_for_status()
        task_id = r.json().get("task_id")
        if not task_id:
            return None
        # poll for completion (max ~5 min)
        for _ in range(60):
            time.sleep(5)
            sr = httpx.get(
                f"https://api.minimax.io/v1/video_generation/{task_id}",
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}"},
                timeout=15.0,
            )
            sr.raise_for_status()
            sd = sr.json()
            status = sd.get("status", "")
            if status == "completed":
                vid_url = sd.get("output", {}).get("url") or sd.get("result", {}).get("url")
                if not vid_url:
                    # try alternative response shapes
                    if "data" in sd and sd["data"]:
                        vid_url = sd["data"][0].get("url")
                if vid_url:
                    vr = httpx.get(vid_url, timeout=120.0)
                    vr.raise_for_status()
                    fname = f"generated_video_{int(time.time())}.mp4"
                    out = DATA_DIR / fname
                    out.write_bytes(vr.content)
                    return out
                return None
            elif status in ("failed", "error"):
                return None
        return None
    except Exception:
        return None


def _gen_video_replicate(prompt: str) -> Path | None:
    """Fallback: generate a video via Replicate API. Returns saved MP4 path or None."""
    try:
        headers = {"Authorization": f"Token {REPLICATE_API_TOKEN}", "Content-Type": "application/json"}
        r = httpx.post(
            "https://api.replicate.com/v1/models/minimax/video-01/predictions",
            headers=headers,
            json={"input": {"prompt": prompt}},
            timeout=30.0,
        )
        r.raise_for_status()
        pred = r.json()
        pred_url = pred.get("urls", {}).get("get") or f"https://api.replicate.com/v1/predictions/{pred['id']}"
        # poll for completion (max ~5 min)
        for _ in range(60):
            time.sleep(5)
            sr = httpx.get(pred_url, headers=headers, timeout=15.0)
            sr.raise_for_status()
            sd = sr.json()
            status = sd.get("status", "")
            if status == "succeeded":
                output = sd.get("output")
                vid_url = output if isinstance(output, str) else (output[0] if isinstance(output, list) and output else None)
                if vid_url:
                    vr = httpx.get(vid_url, timeout=120.0)
                    vr.raise_for_status()
                    fname = f"generated_video_{int(time.time())}.mp4"
                    out = DATA_DIR / fname
                    out.write_bytes(vr.content)
                    return out
                return None
            elif status in ("failed", "canceled"):
                return None
        return None
    except Exception:
        return None


def _generate_media(prompt: str, project_id: str | None):
    """Orchestrator: parse prompt, generate media, import into project, yield NDJSON events."""
    media_type, w, h = _parse_gen_request(prompt)

    yield json.dumps({"type": "tool", "name": f"generate_{media_type}",
                      "args": {"prompt": prompt, "width": w, "height": h}}) + "\n"

    result_path = None
    backend_used = None

    if media_type == "image":
        yield json.dumps({"type": "tool", "name": "generate_image", "args": {"backend": "minimax"}}) + "\n"
        result_path = _gen_image_minimax(prompt, w, h)
        backend_used = "MiniMax"
        if not result_path:
            yield json.dumps({"type": "tool_result", "name": "generate_image",
                              "result": "MiniMax unavailable, trying Pollinations…"}) + "\n"
            result_path = _gen_image_pollinations(prompt, w, h)
            backend_used = "Pollinations"
    else:  # video
        yield json.dumps({"type": "tool", "name": "generate_video", "args": {"backend": "minimax"}}) + "\n"
        result_path = _gen_video_minimax(prompt, w, h)
        backend_used = "MiniMax"
        if not result_path:
            yield json.dumps({"type": "tool_result", "name": "generate_video",
                              "result": "MiniMax unavailable, trying Replicate…"}) + "\n"
            result_path = _gen_video_replicate(prompt)
            backend_used = "Replicate"

    if not result_path or not result_path.exists():
        yield json.dumps({"type": "error", "text": "All generation backends failed. Please try again later."}) + "\n"
        return

    yield json.dumps({"type": "tool_result", "name": f"generate_{media_type}",
                      "result": f"Generated via {backend_used}: {result_path.name}"}) + "\n"

    # Auto-import into the active project
    if project_id:
        try:
            proj = load_project(project_id)
            media_item = import_media_file(proj, result_path, name=result_path.name)
            mid = media_item["id"]
            dur = float(media_item.get("duration") or 3.0)
            clip = {"id": "c" + uuid.uuid4().hex[:8], "media_id": mid, "in": 0, "out": dur, "effects": []}
            proj["clips"].append(clip)
            save_project(proj)
            yield json.dumps({"type": "tool_result", "name": "import_and_add_clip",
                              "result": f"Imported as {mid}, added clip {clip['id']} ({dur:.1f}s)"}) + "\n"
            yield json.dumps({"type": "final",
                              "text": f"✅ Generated {media_type} via {backend_used} and added to timeline. Media ID: {mid}"}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "final",
                              "text": f"✅ Generated {media_type} via {backend_used} ({result_path.name}) but could not auto-import: {e}"}) + "\n"
    else:
        yield json.dumps({"type": "final",
                          "text": f"✅ Generated {media_type} via {backend_used}: {result_path.name}. No active project to import into."}) + "\n"


# --------------------------------------------------------------------------- in-app agent (Ollama)
AGENT_SYSTEM = """You are the Source Montage agent — an AI video editor operating a real timeline.
Respond with EXACTLY ONE JSON object per turn, nothing else:
{"tool":"<tool name>","args":{...}}    or    {"final":"summary of what you did, in one short paragraph"}

Available tools (args in parentheses):
get_projects() · create_project(name) · get_timeline(project_id) · get_media(project_id)
import_media(project_id,path) · add_clips(project_id,clips:[{media_id,in,out,index?}])
trim_clip(project_id,clip_id,in?,out?) · split_clip(project_id,clip_id,at) · move_clip(project_id,clip_id,index)
delete_clip(project_id,clip_id) · add_texts(project_id,texts:[{content,start,end,x,y,size,color}])
delete_text(project_id,text_id) · list_effects() · apply_effect(project_id,clip_id,effect)
remove_effect(project_id,clip_id,effect) · export_project(project_id)
Effects (apply_effect): grayscale sepia vintage cinematic blur sharpen vignette glow warm cool
brighten darken contrast saturate desaturate mirror invert kenburns fadein fadeout.

Rules: ALWAYS call get_timeline first to see the current state. Times are seconds. Work in
small steps and read each result. When the user asks for an export/render, call export_project.
Finish with {"final":"..."} once the request is fully done."""


def _parse_json_obj(raw: str):
    s = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except Exception:
                        return None
    return None


def _ollama_model() -> str | None:
    try:
        names = [m["name"] for m in httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0).json().get("models", [])
                 if "embed" not in m.get("name", "")]
    except Exception:
        return None
    for hint in ("qwen3.5:9b", "qwen3.5:4b", "qwen3.5"):
        for n in names:
            if n.startswith(hint):
                return n
    local = [n for n in names if not n.endswith("cloud")]
    return (local or names or [None])[0]


@app.post("/api/agent")
async def agent(request: Request):
    body = await request.json()
    message = str(body.get("message", "")).strip()
    project_id = body.get("project_id") or None
    selected = (body.get("agent_model") or body.get("model") or "").strip()

    if not message:
        raise HTTPException(400, "message is required")

    # ── Source Gen 1.0: bypass LLM, call generation backends directly ──
    if selected == "Source Gen 1.0":
        return StreamingResponse(_generate_media(message, project_id),
                                 media_type="application/x-ndjson")

    # ── Source Editor: route to gemma4:31b-cloud ──
    if selected == "Source Editor":
        model = "gemma4:31b-cloud"
    else:
        model = _ollama_model()

    if not model:
        raise HTTPException(400, "Ollama not reachable — start it and pull a model")

    def gen():
        messages = [{"role": "system", "content": AGENT_SYSTEM},
                    {"role": "user", "content": (f"Active project_id: {project_id}\n" if project_id else "")
                     + message}]
        for _ in range(24):
            try:
                r = httpx.post(f"{OLLAMA_URL}/api/chat",
                               json={"model": model, "messages": messages, "stream": False,
                                     "think": False, "options": {"num_predict": 900, "temperature": 0.2}},
                               timeout=300.0)
                resp = r.json()
                raw = resp.get("message", {}).get("content", "")
                if not raw:
                    err_msg = resp.get("error") or resp.get("detail") or "Empty response from Ollama"
                    yield json.dumps({"type": "error", "text": str(err_msg)}) + "\n"
                    return
            except Exception as e:
                yield json.dumps({"type": "error", "text": str(e)}) + "\n"
                return
            act = _parse_json_obj(raw)
            if not act:
                yield json.dumps({"type": "final", "text": (raw or "").strip()}) + "\n"
                return
            if "final" in act:
                yield json.dumps({"type": "final", "text": str(act["final"])}) + "\n"
                return
            tool = str(act.get("tool", ""))
            args = act.get("args") or {}
            if project_id and "project_id" not in args and tool not in ("get_projects", "create_project"):
                args["project_id"] = project_id
            yield json.dumps({"type": "tool", "name": tool, "args": args}) + "\n"
            try:
                result = exec_tool(tool, args)
                rtxt = json.dumps(result)[:4000]
            except HTTPException as e:
                rtxt = f"error: {e.detail}"
            except Exception as e:
                rtxt = f"error: {e}"
            yield json.dumps({"type": "tool_result", "name": tool, "result": rtxt[:1500]}) + "\n"
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Result of {tool}:\n{rtxt}"}]
        yield json.dumps({"type": "final", "text": "Step limit reached — ask me to continue."}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# --------------------------------------------------------------------------- static UI
@app.get("/")
def index():
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    return FileResponse(STATIC_DIR / "index.html", headers=headers)


@app.get("/{fname}")
def static_file(fname: str):
    f = STATIC_DIR / Path(fname).name
    if f.exists() and f.is_file():
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
        return FileResponse(f, headers=headers)
    raise HTTPException(404, "not found")
