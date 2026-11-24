# The optional bundled contacts server (Radicale), for people without one.
# See docs/contacts-server.md. Built from PyPI at pinned versions, hash-checked.
FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Same user ID as the FlipDial container, so both can read the setup folder (private files).
RUN useradd --system --uid 10001 --home-dir /nonexistent radicale
COPY docker/contacts-server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt
USER radicale
EXPOSE 5232
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1', 5232), 4).close()"
CMD ["python", "-m", "radicale", "--config", "/data/contacts-server/config"]
