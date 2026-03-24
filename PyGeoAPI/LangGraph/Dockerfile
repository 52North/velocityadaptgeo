
FROM python:3.14-slim

WORKDIR /app

# Install uv
RUN pip install --upgrade pip && pip install uv

# Copy project files
COPY . /app

# Install dependencies
RUN uv sync --frozen --no-cache --python /usr/local/bin/python

# Die virtuelle Umgebung zum Pfad hinzufügen
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/src"
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
