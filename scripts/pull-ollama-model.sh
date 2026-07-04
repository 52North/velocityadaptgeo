#!/bin/sh

set -eu

MODEL="${OLLAMA_MODEL:-nomic-embed-text}"
BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

echo "Waiting for Ollama at ${BASE_URL}..."
until OLLAMA_HOST="${BASE_URL}" ollama list >/dev/null 2>&1; do
  sleep 2
done

echo "Pulling Ollama model: ${MODEL}"
export OLLAMA_HOST="${BASE_URL}"
ollama pull "${MODEL}"
