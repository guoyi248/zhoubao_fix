import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest


@pytest.fixture
def model_service():
    requests_received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests_received.append((self.path, data, self.headers.get("Authorization")))
            output = "你好呀！"
            if data.get("format") or data.get("response_format"):
                output = json.dumps({"summary": "已完成验收。", "achievements": [{"title": "完成验收", "confidence": 1}]})
            result = ({"message": {"content": output}, "eval_count": 5} if self.path == "/api/chat"
                      else {"choices": [{"message": {"content": output}}], "usage": {"total_tokens": 8}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests_received
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
