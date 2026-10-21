FROM python:3.12-slim

WORKDIR /app

RUN pip install --upgrade pip && pip install uv

COPY pyproject.toml uv.lock /app/
RUN uv sync --locked --no-cache

COPY *.py /app/

EXPOSE 8001

CMD ["uv", "run", "--", "python", "app.py"]
