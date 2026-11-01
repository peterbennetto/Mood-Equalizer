"""Run the whole app on your own PC, without the Vercel CLI.

    python dev_server.py

Serves public/ and sends POST /api/reflect to the same handler Vercel
uses. Reads GEMINI_API_KEY and friends from .env. Nothing is written to
disk. Stop it with Ctrl+C.
"""

import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from api.reflect import handler as reflect_handler  # noqa: E402

PORT = int(os.environ.get("PORT", "3000"))


def load_env_file(path):
    """Copy KEY=value lines from a .env file into the environment.

    Real environment variables win. Quotes around values are removed.
    """
    try:
        with open(path, encoding="utf-8-sig") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip("\"'")
        os.environ.setdefault(name.strip(), value)


class DevHandler(SimpleHTTPRequestHandler, reflect_handler):
    """Static files from the first parent, POST /api/reflect from the second."""

    def do_GET(self):
        if self.path.split("?")[0] == "/api/reflect":
            reflect_handler.do_GET(self)
        else:
            SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if self.path.split("?")[0] == "/api/reflect":
            reflect_handler.do_POST(self)
        else:
            self.send_error(404)


def main():
    load_env_file(os.path.join(ROOT, ".env"))
    from api_client import load_settings
    mode = "Gemini" if load_settings()["gemini_key"] else "pre-written lines only"
    handler = partial(DevHandler, directory=os.path.join(ROOT, "public"))
    with ThreadingHTTPServer(("127.0.0.1", PORT), handler) as server:
        print(f"Mood Equalizer on http://localhost:{PORT}  [{mode}]", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
