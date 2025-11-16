# Fixing Ghosting Artifacts in Captured Images

## Problem
Captured images sometimes show ghosting artifacts where subjects appear as "ghosts" or have motion blur from multiple frames blended together.

## Root Causes

1. **H.264 B-frames**: The current H.264 encoding uses B-frames (bidirectional frames) which blend information from multiple frames. When decoded, this can create ghosting artifacts.

2. **Frame Buffering**: OpenCV's VideoCapture buffers frames, and when capturing, you might get frames that are already artifacts from H.264's inter-frame compression.

3. **Inter-frame Compression**: H.264 uses P-frames (predictive) and B-frames that depend on other frames, causing artifacts when motion is present.

## Solutions

### Solution 1: I-Frame Only Encoding (Recommended)
**File**: `scripts/stream_webcam_to_rtsp_iframe_only.sh`

This eliminates ghosting by using only I-frames (intra-frames) which are independently encoded:
- No B-frames (`-bf 0`)
- I-frame every frame (`-g 1`, `keyint=1`)
- Each frame is independently decodable
- No inter-frame compression artifacts

**CPU Usage**: ~30-50% (uses `veryfast` preset)
**Quality**: Excellent for still images
**Bandwidth**: Slightly higher than inter-frame compression, but acceptable

**To use:**
```bash
./scripts/stream_webcam_to_rtsp_iframe_only.sh
```

### Solution 2: Improved Buffer Flushing
**File**: `services/capture/src/capture_service.py`

Enhanced the `capture_best_frame()` method to:
- Flush 10 frames from buffer before capturing (configurable via `CAPTURE_BUFFER_FLUSH`)
- Reduces chance of getting buffered/artifact frames
- Works with any encoding method

**Configuration:**
```bash
export CAPTURE_BUFFER_FLUSH=10  # Number of frames to flush (default: 10)
```

### Solution 3: Reduced OpenCV Buffer
**File**: `services/capture/src/capture_service.py`

Changed OpenCV's frame buffer from 10 to 1:
- Minimizes frame lag
- Ensures freshest frames
- Reduces ghosting from buffered frames

### Solution 4: MJPEG Stream (Alternative)
**File**: `scripts/stream_webcam_to_http_mjpeg.sh`

MJPEG encodes each frame independently (no inter-frame compression):
- Zero ghosting artifacts
- Lower CPU usage (~10-30%)
- Requires changing capture service to use HTTP instead of RTSP

## Recommended Approach

**For best results, use Solution 1 (I-frame only encoding):**

1. Stop current stream:
   ```bash
   pkill -f "ffmpeg.*rtsp"
   ```

2. Start I-frame only stream:
   ```bash
   ./scripts/stream_webcam_to_rtsp_iframe_only.sh
   ```

3. Restart capture service to pick up buffer flushing improvements:
   ```bash
   docker restart bird-monitor-capture
   ```

## Testing

After implementing the fix:
1. Trigger motion detection
2. Check captured images for ghosting
3. Verify images are clean and sharp
4. Monitor CPU usage (should be ~30-50% with I-frame only)

## Configuration Options

All solutions are configurable via environment variables:

```bash
# Buffer flushing (Solution 2)
export CAPTURE_BUFFER_FLUSH=10

# For I-frame only stream, edit the script or use:
export FPS=15
export RESOLUTION=1920x1080
```

## Comparison

| Method | CPU Usage | Ghosting | Quality | Bandwidth |
|--------|-----------|----------|---------|-----------|
| Current (H.264 with B-frames) | ~180% | Yes | Good | Low |
| I-frame only H.264 | ~30-50% | No | Excellent | Medium |
| MJPEG | ~10-30% | No | Excellent | High |

## Notes

- I-frame only encoding is the best balance of quality, CPU usage, and artifact elimination
- The buffer flushing improvement helps with any encoding method
- MJPEG is the lightest CPU option but requires HTTP instead of RTSP

