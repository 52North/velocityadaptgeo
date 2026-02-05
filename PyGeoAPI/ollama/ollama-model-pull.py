import os
import socket
import time
import ollama
import sys

model = os.getenv("OLLAMA_MODEL", "gpt-oss")
OLLAMA_HOST = os.getenv("OLLAMA_HOSTNAME", "ollama")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))


def waiting_for_port(host, port, timeout=180):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Ollama is running at {host}:{port}", flush=True)
                return True
        except OSError:
            print(f"Waiting for Ollama on {host}:{port}…", flush=True)
            time.sleep(1)
    return False


def format_bytes(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}PB"


print(f"Preparing Ollama model: {model}", flush=True)

if not waiting_for_port(OLLAMA_HOST, OLLAMA_PORT):
    raise SystemExit(f"Timeout waiting for Ollama at {OLLAMA_HOST}:{OLLAMA_PORT}")

client = ollama.Client(host=f"http://{OLLAMA_HOST}:{OLLAMA_PORT}")

try:
    response = client.list()

    installed_models = {
        m.get("model") or m.get("name")
        for m in response.get("models", [])
        if m.get("model") or m.get("name")
    }

except Exception as e:
    raise SystemExit(f"Failed to list models from Ollama: {e}")

if model not in installed_models:
    print(f"Downloading model: {model}", flush=True)

    last_percent = -1

    for event in client.pull(model, stream=True):
        status = event.get("status", "")

        completed = event.get("completed")
        total = event.get("total")

        if completed is not None and total:
            percent = int((completed / total) * 100)
            if percent != last_percent:
                last_percent = percent
                sys.stdout.write(
                    f"\r{status}: "
                    f"{format_bytes(completed)} / {format_bytes(total)} "
                    f"({percent}%)"
                )
                sys.stdout.flush()
        else:
            # Non-size status updates (manifest, verifying, etc.)
            print(f"\n{status}", flush=True)

    print("\nDownload complete.", flush=True)
else:
    print(f"Model already present: {model}", flush=True)

# Force-load the model
print(f"Loading model: {model}", flush=True)
client.generate(
    model=model,
    prompt="ping",
    options={"num_predict": 1},
)

print("Ollama is ready and the model is loaded.", flush=True)
