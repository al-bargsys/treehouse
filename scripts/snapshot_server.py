#!/usr/bin/env python3
"""
Simple HTTP server that returns a high-quality JPEG snapshot on demand.
Runs ffmpeg per request to grab one frame from the macOS webcam.
URL: http://0.0.0.0:8083/snapshot.jpg
"""
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import os

PORT = int(os.getenv("SNAPSHOT_PORT", "8083"))
CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "0")
RESOLUTION = os.getenv("SNAPSHOT_RESOLUTION", "1920x1080")
QUALITY = os.getenv("SNAPSHOT_QUALITY", "2")  # 2=high, 31=low
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
# Preview coordination
PREVIEW_HTTP_PORT = os.getenv("PREVIEW_HTTP_PORT", os.getenv("HTTP_PORT", "8082"))
PREVIEW_FPS = os.getenv("PREVIEW_FPS", "7.5")
PREVIEW_WIDTH = os.getenv("PREVIEW_WIDTH", "640")
CAPTURE_RES = os.getenv("CAPTURE_RES", "1280x720")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/snapshot.jpg", "/snapshot"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        # Use coordination script to avoid concurrent camera access with preview.
        # This will briefly stop preview, grab one frame, then restart preview.
        cmd = [
            "bash", os.path.join(SCRIPT_DIR, "snapshot_once.sh")
        ]
        env = os.environ.copy()
        env["CAMERA_DEVICE"] = CAMERA_DEVICE
        env["SNAPSHOT_RESOLUTION"] = RESOLUTION
        env["SNAPSHOT_QUALITY"] = QUALITY
        env["HTTP_PORT"] = PREVIEW_HTTP_PORT
        env["PREVIEW_FPS"] = PREVIEW_FPS
        env["PREVIEW_WIDTH"] = PREVIEW_WIDTH
        env["CAPTURE_RES"] = CAPTURE_RES
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, env=env)
            if proc.returncode != 0 or not proc.stdout:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(proc.stdout)
        except Exception as e:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(f"Snapshot failed: {e}".encode("utf-8"))

    def log_message(self, fmt, *args):
        return

def main():
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Snapshot server listening on http://0.0.0.0:{PORT}/snapshot.jpg")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == "__main__":
    main()


