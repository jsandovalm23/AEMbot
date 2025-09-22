# server.py — servidor HTTP mínimo para Render (healthcheck)
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", "10000"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    # Evita logs ruidosos
    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    httpd = HTTPServer(("", PORT), Handler)
    print(f"[health] listening on :{PORT}")
    httpd.serve_forever()
