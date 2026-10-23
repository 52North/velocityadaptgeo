# Laya decision model (https://huggingface.co/convaiinnovations/laya) behind `laya-serve`
# (POST /v1/systemone, GET /health), on CPU. See metrics/.docs/laya_finetune_plan.md.
FROM python:3.12-slim

# Both pinned: laya releases almost daily. Torch first, from the CPU index, so laya's
# `torch>=2.0` is already met and pip does not pull the multi-GB CUDA wheels.
ARG TORCH_VERSION=2.14.0
ARG LAYA_VERSION=0.4.12
RUN pip install --no-cache-dir "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "laya[serve]==${LAYA_VERSION}" \
    && pip check

# TORCH_DISABLE_NATIVE_JIT: torch 2.14 otherwise compiles Triton kernels on the first inference,
# which needs a C compiler this image does not have (laya #365). USE_TF=0: TensorFlow's runtime
# can deadlock model construction.
ENV TORCH_DISABLE_NATIVE_JIT=1 \
    USE_TF=0 \
    PYTHONUNBUFFERED=1 \
    TOKENIZERS_PARALLELISM=false \
    LAYA_DEVICE=cpu \
    HF_HOME=/home/laya/.cache/huggingface

RUN useradd --uid 10001 --create-home laya \
    && mkdir -p /home/laya/.cache/huggingface \
    && chown -R laya:laya /home/laya/.cache
USER laya

EXPOSE 8000

CMD ["laya-serve"]
