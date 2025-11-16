#!/usr/bin/env python3
"""
MJPEG HTTP server that proxies FFmpeg stream and binds to all interfaces.
This ensures Docker can access the camera stream.
"""
import http.server
import socketserver
import subprocess
import sys
import signal
import os
import time

HTTP_PORT = int(os.getenv('HTTP_PORT', 8082))
CAMERA_DEVICE = os.getenv('CAMERA_DEVICE', '0')
PREVIEW_FPS = os.getenv('PREVIEW_FPS', '7.5')
PREVIEW_WIDTH = os.getenv('PREVIEW_WIDTH', '640')
CAPTURE_RES = os.getenv('CAPTURE_RES', '1280x720')
PREVIEW_Q = os.getenv('PREVIEW_Q', '7')

# FFmpeg command - output to stdout as MJPEG stream
# Use image2pipe format to get individual JPEG frames that we can wrap in multipart
FFMPEG_CMD = [
    'ffmpeg',
    '-hide_banner',
    '-loglevel', 'warning',
    '-f', 'avfoundation',
    '-framerate', PREVIEW_FPS,
    '-video_size', CAPTURE_RES,
    '-pixel_format', 'uyvy422',
    '-i', f'{CAMERA_DEVICE}:none',
    '-vf', f'scale={PREVIEW_WIDTH}:-2,format=yuvj422p',
    '-c:v', 'mjpeg',
    '-q:v', PREVIEW_Q,
    '-r', PREVIEW_FPS,
    '-f', 'image2pipe',
    '-vcodec', 'mjpeg',
    '-'  # Output to stdout
]

ffmpeg_proc = None

def cleanup(signum, frame):
    """Clean up FFmpeg process on exit."""
    global ffmpeg_proc
    if ffmpeg_proc:
        ffmpeg_proc.terminate()
        ffmpeg_proc.wait()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

class MJPEGHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        if self.path == '/preview.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=ffmpeg')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/preview.mjpg':
            try:
                # Send response headers for MJPEG stream
                # OpenCV expects proper MJPEG stream format
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=ffmpeg')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.send_header('Connection', 'close')
                self.end_headers()
                
                # Read JPEG frames from FFmpeg and wrap them in multipart format
                # FFmpeg outputs individual JPEG frames via image2pipe
                try:
                    import select
                    
                    # JPEG frame markers
                    JPEG_SOI = b'\xff\xd8'  # Start of Image
                    JPEG_EOI = b'\xff\xd9'  # End of Image
                    
                    buffer = b''
                    while True:
                        # Check if FFmpeg is still running
                        if ffmpeg_proc.poll() is not None:
                            break
                        
                        # Read data from FFmpeg
                        ready, _, _ = select.select([ffmpeg_proc.stdout], [], [], 0.1)
                        if ready:
                            chunk = ffmpeg_proc.stdout.read(8192)
                            if chunk:
                                buffer += chunk
                                
                                # Look for complete JPEG frames (SOI ... EOI)
                                while JPEG_SOI in buffer and JPEG_EOI in buffer:
                                    soi_pos = buffer.find(JPEG_SOI)
                                    eoi_pos = buffer.find(JPEG_EOI, soi_pos)
                                    
                                    if eoi_pos != -1:
                                        # Found complete frame
                                        frame = buffer[soi_pos:eoi_pos + 2]
                                        buffer = buffer[eoi_pos + 2:]
                                        
                                        # Write multipart boundary and frame
                                        boundary = b'\r\n--ffmpeg\r\n'
                                        header = b'Content-Type: image/jpeg\r\nContent-Length: ' + str(len(frame)).encode() + b'\r\n\r\n'
                                        self.wfile.write(boundary + header + frame)
                                        self.wfile.flush()
                                    else:
                                        # Incomplete frame, wait for more data
                                        break
                            else:
                                # EOF from FFmpeg
                                break
                except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                    # Client disconnected or pipe closed - that's fine
                    pass
            except Exception as e:
                print(f"Error serving stream: {e}", file=sys.stderr)
                try:
                    self.send_error(503, "Stream unavailable")
                except:
                    pass
        else:
            self.send_error(404, "Not found")
    
    def log_message(self, format, *args):
        # Suppress access logs
        pass

if __name__ == "__main__":
    # Start FFmpeg process - output to stdout
    print(f"Starting FFmpeg...", file=sys.stderr)
    ffmpeg_proc = subprocess.Popen(
        FFMPEG_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0  # Unbuffered
    )
    
    # Wait a moment for FFmpeg to start
    time.sleep(2)
    
    # Check if FFmpeg is still running
    if ffmpeg_proc.poll() is not None:
        stderr = ffmpeg_proc.stderr.read().decode('utf-8', errors='ignore')
        print(f"FFmpeg failed to start: {stderr}", file=sys.stderr)
        sys.exit(1)
    
    # Start HTTP server on all interfaces
    print(f"MJPEG server listening on 0.0.0.0:{HTTP_PORT}", file=sys.stderr)
    print(f"Stream available at: http://0.0.0.0:{HTTP_PORT}/preview.mjpg", file=sys.stderr)
    
    with socketserver.TCPServer(("0.0.0.0", HTTP_PORT), MJPEGHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...", file=sys.stderr)
        finally:
            cleanup(None, None)

