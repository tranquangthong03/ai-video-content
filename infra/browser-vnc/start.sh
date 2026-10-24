#!/bin/sh
# Headful Chromium on a virtual display, exposed via noVNC (6080) and CDP (9222).
set -e

Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" -nolisten tcp &
sleep 1

# No VNC password: the port must only be reachable on a trusted network / behind a proxy.
x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 &

# Chromium only listens on 127.0.0.1:9223; nginx republishes CDP on 0.0.0.0:9222 (see nginx-cdp.conf).
nginx -g 'daemon off;' &

# Chromium is the main process: if it dies the container exits and gets restarted.
exec chromium \
    --no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check \
    --remote-debugging-port=9223 --remote-allow-origins=* \
    --user-data-dir=/tmp/chromium-profile \
    --window-position=0,0 --window-size=1280,900 \
    about:blank
