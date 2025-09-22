# server.py — HTTP mínimo para Render (responde / y /healthz)
from http.server import BaseHTTPRequestHandler, HTTPServer
import os

PORT = int(os.getenv("PORT", "10000"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK"
        if self.path == "/":
            body = b"AEM bot is running"
        elif self.path == "/healthz":
            body = b"healthy"

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run():
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)
    httpd.serve_forever()

if __name__ == "__main__":
    run()
