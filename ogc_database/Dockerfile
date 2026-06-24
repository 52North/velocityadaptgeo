FROM python:3.12-slim

WORKDIR /app

# Install uv (https://github.com/astral-sh/uv)
RUN pip install --upgrade pip && pip install uv

COPY ./ /app
COPY ./pyproject.toml /app/pyproject.toml

RUN uv sync

EXPOSE 8001

CMD ["uv", "run", "--", "python", "app.py"]
