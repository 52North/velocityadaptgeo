FROM ollama/ollama

RUN apt-get update && \
    apt-get install -y \
    python3 \
    python3-pip \
    python3-setuptools \
    gcc \
    python3-dev \
    && apt-get clean

RUN pip3 install ollama

# Setup for fetching ollama models
ADD docker-entrypoint.py /
ENTRYPOINT ["/usr/bin/python3","docker-entrypoint.py"]
