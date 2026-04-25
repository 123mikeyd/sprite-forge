#!/usr/bin/env python3
"""Sprite Forge — simple server that serves the UI + output files."""
import os, json
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 5001
APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(APP_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/ui.html"
        super().do_GET()

    def log_message(self, format, *args):
        pass  # quiet

print(f"Sprite Forge: http://localhost:{PORT}")
print(f"Output dir: {OUTPUT_DIR}")
HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
