"""FinCompass desktop launcher.

Windowed app: no console window. Runs the local FinCompass server in a background
thread and shows a small always-available control window with Open and Quit
buttons. Quitting (or closing the window) shuts the server down gracefully.

PyInstaller compiles this into a standalone windowed executable (see
build_exe.bat / the Inno Setup installer). Running it directly with Python also
works.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def _resource_root() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


# --- persistent, writable data dir next to the executable (frozen builds) ----
if getattr(sys, "frozen", False):
    _base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.dirname(sys.executable)
    # Honor an explicit FINCOMPASS_DATA_DIR override for the WHOLE data dir
    # (including the model registry), so a clean-environment launch is truly
    # isolated and does not reuse %LOCALAPPDATA%\FinCompass state.
    _data_dir = os.environ.get("FINCOMPASS_DATA_DIR") or os.path.join(_base, "FinCompass")
    os.makedirs(_data_dir, exist_ok=True)
    os.environ.setdefault("FINCOMPASS_DATA_DIR", _data_dir)
    # Onefile builds run from an ephemeral extraction dir, so models trained via
    # the in-app builder must be written somewhere persistent — otherwise they
    # vanish on exit. Point the model registry at a writable per-user location.
    _models_dir = os.environ.get("FINCOMPASS_MODELS_DIR") or os.path.join(_data_dir, "models")
    os.makedirs(_models_dir, exist_ok=True)
    os.environ.setdefault("FINCOMPASS_MODELS_DIR", _models_dir)
    # Seed the bundled shipped models (e.g. the validated_research monthly
    # reference model) into the writable registry. On first run this makes a
    # usable model available; on UPGRADE it refreshes a shipped model artifact
    # whose content changed (e.g. an updated manifest / applicability_domain).
    # User-trained models never exist in the bundle, so they are never touched.
    try:
        import shutil

        def _differs(a, b):
            try:
                if os.path.getsize(a) != os.path.getsize(b):
                    return True
                with open(a, "rb") as fa, open(b, "rb") as fb:
                    return fa.read() != fb.read()
            except Exception:
                return True

        _bundled_models = os.path.join(_resource_root(), "models")
        if os.path.isdir(_bundled_models):
            for _name in os.listdir(_bundled_models):
                _src = os.path.join(_bundled_models, _name)
                _dst = os.path.join(_models_dir, _name)
                # active_model.json is per-user activation state, never seeded.
                if _name == "active_model.json" or not os.path.isfile(_src):
                    continue
                if not os.path.exists(_dst) or _differs(_src, _dst):
                    shutil.copy2(_src, _dst)
    except Exception:
        pass
    # A windowed build has no console; give stdout/stderr (and thus logging) a
    # file to write to so nothing errors on a None stream.
    try:
        _logdir = os.path.join(_data_dir, "logs")
        os.makedirs(_logdir, exist_ok=True)
        _logf = open(os.path.join(_logdir, "fincompass.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = _logf
        sys.stderr = _logf
    except Exception:
        pass

# Read bundled resources (static/, legal/, config/, models/...) from the root.
os.chdir(_resource_root())

HOST = os.environ.get("FINCOMPASS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FINCOMPASS_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"


def main() -> None:
    import uvicorn
    from api import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    def _open_when_ready() -> None:
        for _ in range(80):
            if getattr(server, "started", False):
                break
            time.sleep(0.25)
        webbrowser.open(URL)

    threading.Thread(target=_open_when_ready, daemon=True).start()

    # --- small control window (no console) ---
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("FinCompass")
        root.geometry("360x190")
        root.resizable(False, False)

        tk.Label(root, text="FinCompass is running", font=("Segoe UI", 13, "bold")).pack(pady=(18, 2))
        tk.Label(root, text=URL, fg="#1a73e8", font=("Segoe UI", 10)).pack()
        tk.Label(
            root,
            text="Your browser should open automatically.\nKeep this window open; click Quit to stop.",
            fg="#555", justify="center", font=("Segoe UI", 9),
        ).pack(pady=(6, 12))

        row = tk.Frame(root)
        row.pack()
        tk.Button(row, text="Open in browser", width=15, command=lambda: webbrowser.open(URL)).grid(row=0, column=0, padx=6)

        def quit_app() -> None:
            server.should_exit = True
            root.after(400, root.destroy)

        tk.Button(row, text="Quit FinCompass", width=15, command=quit_app).grid(row=0, column=1, padx=6)
        root.protocol("WM_DELETE_WINDOW", quit_app)
        root.mainloop()
        server.should_exit = True
    except Exception:
        # No GUI available (e.g. launched headless): just keep the server up.
        try:
            while server_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True


if __name__ == "__main__":
    main()
