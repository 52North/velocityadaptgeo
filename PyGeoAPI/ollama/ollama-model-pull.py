import os
import socket
import time
import ollama

model = os.getenv("OLLAMA_MODEL", "gpt-oss")
OLLAMA_HOST = os.getenv("OLLAMA_HOSTNAME", "ollama")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))


def waiting_for_port(host, port, timeout=120):
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            return False

        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Ollama is running at {host}:{port}")
                return True
        except OSError:
            print(f"Waiting for ollama on {host}:{port}")
            time.sleep(1)


if __name__ == "__main__":
    if not waiting_for_port(OLLAMA_HOST, OLLAMA_PORT, timeout=180):
        raise SystemExit(f"Timeout waiting for ollama at {OLLAMA_HOST}:{OLLAMA_PORT}")

    client = ollama.Client(host=f"http://{OLLAMA_HOST}:{OLLAMA_PORT}")

    try:
        response = client.list()
        installed_models = {m["name"] for m in response.get("models", [])}
    except Exception as e:
        raise SystemExit(f"Failed to list models from ollama: {e}")

    if model not in installed_models:
        print(f"Downloading model {model}")
        client.pull(model)

    # Force-load the model by making a minimal request
    print(f"Loading model {model}")
    client.generate(
        model=model,
        prompt="ping",
        options={"num_predict": 1},
    )

    print("Ollama is serving and the model is loaded")
