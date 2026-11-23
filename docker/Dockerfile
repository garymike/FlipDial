# Build the web app
FROM node:26-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Runtime
FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FLIPDIAL_HOST=0.0.0.0 FLIPDIAL_DATA_DIR=/data FLIPDIAL_WEB_DIR=/app/web
RUN useradd --system --uid 10001 --home-dir /nonexistent flipdial
WORKDIR /app
COPY backend/ ./backend/
# Install exactly the locked, hash-checked dependencies, then FlipDial itself.
RUN pip install --no-cache-dir uv==0.11.32 \
 && uv export --project backend --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
 && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
 && pip install --no-cache-dir --no-deps ./backend \
 && pip uninstall -y uv && rm /tmp/requirements.txt
COPY --from=web /web/dist ./web
RUN mkdir -p /data && chown flipdial /data
USER flipdial
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"
CMD ["flipdial"]
