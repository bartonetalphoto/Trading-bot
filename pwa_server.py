"""
PWA Static File Server
=======================
Serves the BotTrader PWA from the /app folder.
Runs on a separate port alongside the bot API.
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

pwa = FastAPI()
APP_DIR = Path(__file__).parent / "app"

pwa.mount("/static", StaticFiles(directory=str(APP_DIR)), name="static")

@pwa.get("/")
def serve_index():
    return FileResponse(str(APP_DIR / "index.html"))

@pwa.get("/{path:path}")
def serve_file(path: str):
    file_path = APP_DIR / path
    if file_path.exists():
        return FileResponse(str(file_path))
    return FileResponse(str(APP_DIR / "index.html"))
