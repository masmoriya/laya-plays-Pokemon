"""The offline Jev: research/01 section 3's server, with option-aware choices.

Answers come from `fake_answers.json`, keyed by question name. A choice answer names an
option id that may or may not be legal for the branch under test, which is how
`test_battle_fixture.py` exercises the fallback. No key, no network, no ROM.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
ANSWERS = json.loads((HERE / "fake_answers.json").read_text())


def make_handler(answers):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            out = json.dumps(
                {
                    "model": body.get("model", "jev-latest"),
                    "answers": {
                        n: answers[n] for n in body.get("questions", {}) if n in answers
                    },
                    "usage": {
                        "input_tokens": len(json.dumps(body)) // 4,
                        "output_tokens": 0,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    return Handler


def serve(answers=None, port=0):
    """Start on a background thread. Returns (base_url, shutdown)."""
    server = HTTPServer(("127.0.0.1", port), make_handler(answers or ANSWERS))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}", server.shutdown


if __name__ == "__main__":
    url, _ = serve(port=int(os.environ.get("PORT", 4321)))
    print(f"fake jev on {url}")
    threading.Event().wait()
