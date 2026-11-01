"""Vercel function: POST /api/reflect

A thin HTTP shell. The work is done by handle_reflect() in api_client.py.
The Gemini key is read from the GEMINI_API_KEY environment variable here
on the server. It never reaches the browser.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# api_client.py, mood_logic.py and responses.py live in the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import MAX_BODY_BYTES, handle_reflect  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "Request too large."})
            return
        status, payload = handle_reflect(self.rfile.read(length))
        self._send_json(status, payload)

    def do_GET(self):
        self._send_json(405, {"error": "Use POST."}, {"Allow": "POST"})

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
