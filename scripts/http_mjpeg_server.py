#!/usr/bin/env python3
"""
Simple HTTP server for MJPEG streaming.
Reads MJPEG data from stdin (piped from ffmpeg) and serves it via HTTP.
"""
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

class MJPEGHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves MJPEG stream."""
    
    def do_GET(self):
        """Handle GET requests for MJPEG stream."""
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=ffmpeg')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            
            # Stream MJPEG frames from stdin
            try:
                while True:
                    # Read frame data (this is a simplified version)
                    # In practice, we'd need to properly parse MJPEG boundaries
                    chunk = sys.stdin.buffer.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Client disconnected
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

def run_server(port=8081):
    """Run the HTTP server."""
    server = HTTPServer(('0.0.0.0', port), MJPEGHandler)
    print(f"HTTP MJPEG server started on port {port}")
    print(f"Stream available at: http://localhost:{port}/stream.mjpg")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    run_server(port)

