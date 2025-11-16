#!/usr/bin/env python3
"""
Simple HTTP proxy for camera stream to make it accessible from Docker.
Reads from FFmpeg MJPEG stream and serves it via HTTP on all interfaces.
"""
import http.server
import socketserver
import urllib.request
import sys

STREAM_URL = "http://localhost:8082/preview.mjpg"
PROXY_PORT = 8084

class CameraProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        if self.path == '/preview.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=ffmpeg')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/preview.mjpg':
            try:
                # Open connection to FFmpeg stream
                stream = urllib.request.urlopen(STREAM_URL, timeout=10)
                
                # Send headers
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=ffmpeg')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()
                
                # Stream data
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    
            except Exception as e:
                print(f"Error proxying stream: {e}", file=sys.stderr)
                self.send_error(503, "Stream unavailable")
        else:
            self.send_error(404, "Not found")
    
    def log_message(self, format, *args):
        # Suppress access logs
        pass

if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PROXY_PORT), CameraProxyHandler) as httpd:
        print(f"Camera proxy listening on 0.0.0.0:{PROXY_PORT}")
        print(f"Proxying: {STREAM_URL}")
        print(f"Access from Docker: http://host.docker.internal:{PROXY_PORT}/preview.mjpg")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down proxy...")

