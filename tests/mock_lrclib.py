"""Minimal LRCLIB-compatible server for offline tests: python3 tests/mock_lrclib.py 8765"""

import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

SYNCED = """[ar:Void Test]
[ti:Everything You Are]
[00:01.00]Can you hear the signal
[00:04.00]<00:04.00>You <00:04.60>could <00:05.20>be <00:05.80>everything <00:07.00>
[00:08.00]Come back to me
[00:11.00]Am I sinking or am I swimming
[00:15.00]
[00:17.00]Is it love or is it noise
[00:21.00]Or can I just be myself?
[00:25.00]Everything, everything
"""

RECORDS = [
    {"id": 1, "trackName": "Everything You Are", "artistName": "Void Test", "albumName": "Signal Lost",
     "duration": 30, "instrumental": False, "plainLyrics": "...", "syncedLyrics": SYNCED},
]


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.server.hits.append((u.path, q))
        if u.path == "/api/get":
            rec = next((r for r in RECORDS if r["trackName"].lower() == q.get("track_name", "").lower()
                        and abs(r["duration"] - float(q.get("duration", 0))) <= 2), None)
            return self._send(rec, 404 if rec is None else 200)
        if u.path == "/api/search":
            return self._send([r for r in RECORDS if q.get("track_name", "").lower() in r["trackName"].lower()])
        self._send({"error": "not found"}, 404)

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H)
    srv.hits = []
    srv.serve_forever()
