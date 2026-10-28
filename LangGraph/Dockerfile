# The version in .python-version, which local runs and uv.lock use.
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install --upgrade pip && pip install uv

# Copy project files
COPY . /app

# Install dependencies
RUN uv sync --locked --no-cache --python /usr/local/bin/python

# Die virtuelle Umgebung zum Pfad hinzufügen
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/src"
# The container runs unprivileged on a read-only root filesystem (docker-compose.yml): /tmp is
# the only writable place besides mounted volumes, so uv's cache and $HOME go there, and
# `uv run` uses the environment synced above instead of syncing again.
ENV HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1
# Not root. Compose overrides the ids to match the owner of the mounted metrics/ (SETUP.md).
USER 1000:1000
EXPOSE 8000

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
