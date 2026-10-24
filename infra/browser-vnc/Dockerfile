FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    SCREEN_GEOMETRY=1280x900x24

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium xvfb x11vnc novnc websockify nginx curl ca-certificates \
        fonts-liberation fonts-noto-color-emoji fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default \
    && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

COPY nginx-cdp.conf /etc/nginx/conf.d/cdp.conf
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# noVNC 6080, Chrome DevTools (CDP) 9222
EXPOSE 6080 9222

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fs http://localhost:6080/vnc.html >/dev/null && curl -fs http://localhost:9222/json/version >/dev/null || exit 1

CMD ["/usr/local/bin/start.sh"]
