# Camera Connection Fix for Docker on macOS

## Problem
Docker containers can't connect to the camera stream running on the host via `host.docker.internal`.

## Solution: Use Host IP Address

Instead of using `host.docker.internal`, use your Mac's actual IP address:

1. **Find your Mac's IP address**:
   ```bash
   ifconfig | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}' | head -1
   ```

2. **Set CAMERA_URL environment variable**:
   ```bash
   export CAMERA_URL="http://YOUR_IP:8082/preview.mjpg"
   docker compose up -d capture-service
   ```

   Or edit `docker-compose.yml` and set:
   ```yaml
   - CAMERA_URL=http://192.168.x.x:8082/preview.mjpg
   ```

3. **Restart the capture service**:
   ```bash
   docker compose restart capture-service
   ```

## Alternative: Use Camera Proxy

A proxy script is available at `scripts/camera_proxy.py` that should make the stream accessible from Docker. To use it:

1. Make sure the preview stream is running:
   ```bash
   ./scripts/start_preview_and_snapshot.sh
   ```

2. The proxy should start automatically (port 8084)

3. The capture service is configured to use port 8084 by default

## Troubleshooting

- Check if the stream is accessible on localhost: `curl http://localhost:8082/preview.mjpg`
- Check if Docker can resolve host.docker.internal: `docker exec bird-monitor-capture getent hosts host.docker.internal`
- Check firewall settings: `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate`
- Try using the gateway IP (usually 192.168.65.254 on Docker Desktop for Mac)

