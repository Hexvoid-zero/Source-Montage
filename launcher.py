"""Source Montage launcher — standalone desktop app window (suite pattern).

Splash instantly, uvicorn in a daemon thread, pywebview (WebView2) window; falls back to
the default browser. Port 19790 (mirrors Palmier Pro's 19789 — the MCP endpoint lives at
http://127.0.0.1:19790/mcp so agents can edit the timeline while the app is open).
"""
import os
import sys
import threading
import time
from pathlib import Path

_SPLASH = """\
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Source Montage</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1A1614;display:flex;align-items:center;justify-content:center;height:100vh;
font-family:-apple-system,"Segoe UI",Roboto,sans-serif;color:#FDFCFB;overflow:hidden}
.wrap{text-align:center}
.logo{font-size:64px;color:#F59E0B;text-shadow:0 0 24px rgba(245,158,11,.6);margin-bottom:18px;animation:pulse 2s ease-in-out infinite}
h1{font-size:22px;font-weight:700;margin-bottom:8px}h1 span{color:#F59E0B}
p{font-size:13px;color:#8C827D;margin-bottom:30px}
.bar{width:210px;height:3px;background:#2D2724;border-radius:3px;margin:0 auto;overflow:hidden;position:relative}
.bar::after{content:'';position:absolute;left:-40%;top:0;width:40%;height:100%;
background:linear-gradient(90deg,transparent,#F59E0B,#FCD34D,transparent);animation:slide 1.2s ease-in-out infinite}
@keyframes slide{0%{left:-40%}100%{left:100%}}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
</style></head><body><div class="wrap"><div class="logo">▣</div>
<h1>Source<span>Montage</span></h1><p>Cutting the timeline…</p><div class="bar"></div></div></body></html>
"""


def main():
    if getattr(sys, "frozen", False):
        os.environ.setdefault("SOURCE_MONTAGE_STATIC", str(Path(sys._MEIPASS) / "static"))

    data_dir = Path(os.getenv("SOURCE_MONTAGE_DATA") or (Path(os.getenv("LOCALAPPDATA") or Path.home()) / "SourceMontage"))
    data_dir.mkdir(parents=True, exist_ok=True)
    logfile = data_dir / "source-montage.log"

    def log(msg):
        try:
            with logfile.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    if sys.stdout is None or sys.stderr is None:
        _log = open(logfile, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log

    log("launcher start")
    port = int(os.getenv("SOURCE_MONTAGE_PORT", "19790"))
    url = f"http://127.0.0.1:{port}"

    try:
        if os.getenv("SOURCE_MONTAGE_HEADLESS") == "1":
            raise RuntimeError("headless requested")

        import webview

        window = webview.create_window("Source Montage", html=_SPLASH,
                                       width=1360, height=880, min_size=(1000, 640))

        def _on_gui_ready():
            def _boot():
                try:
                    import httpx
                    import uvicorn
                    from server import app
                    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
                    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
                    for _ in range(300):
                        try:
                            if httpx.get(url + "/api/ping", timeout=1.0).status_code == 200:
                                break
                        except Exception:
                            time.sleep(0.05)
                    log(f"ready — {url}")
                    window.load_url(url)
                except Exception as e:
                    import traceback
                    log(f"BOOT EXCEPTION: {e}\n{traceback.format_exc()}")

            threading.Thread(target=_boot, daemon=True).start()

        webview.start(func=_on_gui_ready, gui="edgechromium")

    except Exception as e:
        log(f"native window unavailable ({e}); browser fallback")
        import httpx
        import uvicorn
        from server import app
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
        for _ in range(300):
            try:
                if httpx.get(url + "/api/ping", timeout=1.0).status_code == 200:
                    break
            except Exception:
                time.sleep(0.05)
        if os.getenv("SOURCE_MONTAGE_HEADLESS") != "1":
            import webbrowser
            webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    os._exit(0)


if __name__ == "__main__":
    main()
