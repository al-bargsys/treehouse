#!/bin/bash
# Start RTSP server using mediamtx (rtsp-simple-server)
# This provides a proper RTSP server for FFmpeg to stream to

set -e

RTSP_PORT=${RTSP_PORT:-8554}
HTTP_PORT=${HTTP_PORT:-9997}

# Check if mediamtx is installed
if ! command -v mediamtx &> /dev/null; then
    echo "MediaMTX (RTSP server) is not installed"
    echo ""
    echo "Install with:"
    echo "  brew install mediamtx"
    echo ""
    echo "Or download from: https://github.com/bluenviron/mediamtx"
    exit 1
fi

echo "Starting MediaMTX RTSP server..."
echo "  RTSP Port: ${RTSP_PORT}"
echo "  HTTP Port: ${HTTP_PORT}"
echo ""
echo "Streams will be available at:"
echo "  rtsp://localhost:${RTSP_PORT}/webcam"
echo "  rtsp://localhost:${RTSP_PORT}/webcam-live"
echo "  rtsp://localhost:${RTSP_PORT}/webcam-hi"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Create minimal mediamtx config if it doesn't exist
CONFIG_FILE="${HOME}/.mediamtx.yml"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
rtspAddress: :${RTSP_PORT}
rtspTransports: [tcp, udp]
rtspEncryption: "no"
logLevel: info
logDestinations: [stdout]
logFile: ""
paths:
  webcam:
    source: publisher
  webcam-live:
    source: publisher
  webcam-hi:
    source: publisher
EOF
    echo "Created MediaMTX config at: $CONFIG_FILE"
else
    # Fix deprecated/invalid fields
    echo "Updating config file to use current MediaMTX format..."
    # Remove invalid fields
    sed -i.bak -e '/^serverName:/d' \
               -e '/^sourceOnDemand:/d' \
               -e '/^sourceOnDemandStartTimeout:/d' \
               -e '/^sourceOnDemandCloseAfter:/d' \
               "$CONFIG_FILE"
    # Update deprecated fields
    sed -i.bak -e 's/^protocols:/rtspTransports:/' \
               -e 's/^encryption:/rtspEncryption:/' \
               "$CONFIG_FILE"
    # Ensure source is set correctly
    if ! grep -q "source: publisher" "$CONFIG_FILE"; then
        # Add source if path exists but source is missing
        sed -i.bak '/^  webcam:/a\    source: publisher' "$CONFIG_FILE"
    fi
    # Ensure webcam-live path exists
    if ! grep -q "^  webcam-live:" "$CONFIG_FILE"; then
        printf "\n  webcam-live:\n    source: publisher\n" >> "$CONFIG_FILE"
    fi
    # Ensure webcam-hi path exists
    if ! grep -q "^  webcam-hi:" "$CONFIG_FILE"; then
        printf "\n  webcam-hi:\n    source: publisher\n" >> "$CONFIG_FILE"
    fi
    echo "Config file updated"
fi

# Start mediamtx
mediamtx "$CONFIG_FILE"

