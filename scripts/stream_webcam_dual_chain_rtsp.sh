#!/bin/bash
# Dual RTSP using chaining:
# 1) Camera -> Hi-quality I-frame-only (webcam-hi)
# 2) Re-encode from webcam-hi -> Live low-bitrate HW-encoded (webcam-live)
#
# Advantage: camera is opened once, second leg pulls from RTSP, avoiding device conflicts.

set -e

RTSP_SERVER=${RTSP_SERVER:-localhost:8554}
HI_PATH=${HI_PATH:-webcam-hi}
LIVE_PATH=${LIVE_PATH:-webcam-live}
CAMERA_DEVICE=${CAMERA_DEVICE:-0}
RESOLUTION=${RESOLUTION:-1920x1080}
FPS=${FPS:-15}
HI_URL="rtsp://${RTSP_SERVER}/${HI_PATH}"
LIVE_URL="rtsp://${RTSP_SERVER}/${LIVE_PATH}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Dual RTSP (Chained) - Hi then Live"
echo "=========================================="
echo "Hi URL   : ${HI_URL}"
echo "Live URL : ${LIVE_URL}"
echo ""

if ! command -v ffmpeg &>/dev/null; then
  echo "FFmpeg not installed."
  exit 1
fi

if ! nc -z localhost 8554 2>/dev/null; then
  echo -e "${YELLOW}RTSP server not running on :8554${NC}"
  exit 1
fi

echo -e "${GREEN}Starting hi-quality publisher...${NC}"
ffmpeg -hide_banner -loglevel warning \
  -f avfoundation -framerate ${FPS} -video_size ${RESOLUTION} -i "${CAMERA_DEVICE}:none" \
  -c:v libx264 -preset veryfast -tune stillimage -profile:v high -pix_fmt yuv420p \
  -b:v 8M -maxrate 10M -bufsize 20M \
  -g 1 -keyint_min 1 -bf 0 \
  -x264-params "keyint=1:min-keyint=1:scenecut=0:force-cfr=1:ref=1:me=hex:subme=4:trellis=0:fast-pskip=1:level=5.2" \
  -f rtsp -rtsp_transport tcp -rtsp_flags prefer_tcp "${HI_URL}" \
  >/tmp/hi_rtsp.log 2>&1 &
HI_PID=$!
echo "hi publisher pid: ${HI_PID}"

sleep 3

echo -e "${GREEN}Starting live re-encoder from hi stream...${NC}"
ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp -i "${HI_URL}" \
  -c:v h264_videotoolbox -realtime 1 -b:v 2500k -maxrate 3000k -bufsize 6000k \
  -g $((FPS * 2)) -bf 0 -pix_fmt yuv420p \
  -f rtsp -rtsp_transport tcp -rtsp_flags prefer_tcp "${LIVE_URL}" \
  >/tmp/live_rtsp.log 2>&1 &
LIVE_PID=$!
echo "live re-encoder pid: ${LIVE_PID}"

echo ""
echo "Logs:"
echo " tail -f /tmp/hi_rtsp.log"
echo " tail -f /tmp/live_rtsp.log"
echo ""
echo "Stop with: kill ${HI_PID} ${LIVE_PID}"


