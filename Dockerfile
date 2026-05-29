FROM nvcr.io/nvidia/cuda:12.8.0-base-ubuntu24.04

# Ubuntu 24.04 ships Python 3.12 which satisfies requires-python>=3.11
RUN apt-get update -q && \
    apt-get install -y -q python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
# torch>=2.12 requires CUDA 13+; pin <2.12 for CUDA 12.8 (RTX 3060)
RUN pip3 install --break-system-packages "torch>=2.6,<2.12" \
    --index-url https://download.pytorch.org/whl/cu128 \
    --extra-index-url https://pypi.org/simple/
# pip won't reinstall already-satisfied torch; rest from PyPI
RUN pip3 install --break-system-packages ".[gpu]"

COPY src/ ./src/

CMD ["uvicorn", "curriculum_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
