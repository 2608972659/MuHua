# ==========================================
# 阶段 1: Nuitka 编译源码 + 预下载模型
# ==========================================
FROM python:3.10-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /build

# Nuitka 编译需要的 C/C++ 工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    patchelf \
    ccache \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ==============================
# Layer 1: Python 依赖（改 requirements.txt 才重装）
# ==============================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir nuitka

# ==============================
# Layer 2: 模型下载（改 EMB_MODEL 才重下）
# ==============================
ENV EMB_MODEL_DOWNLOAD="BAAI/bge-base-zh-v1.5"
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
import os; \
model_name = os.getenv('EMB_MODEL_DOWNLOAD', 'BAAI/bge-base-zh-v1.5'); \
print(f'预下载模型: {model_name}'); \
SentenceTransformer(model_name); \
print('模型下载完成') \
"

# ==============================
# Layer 3: Nuitka 编译（改 .py 源码才重编）
# ==============================
COPY . .
RUN for f in *.py; do \
        echo "Nuitka compiling: $f"; \
        python -m nuitka --module "$f"; \
    done \
    && rm -f *.py

# ==========================================
# 阶段 2: 生产运行（无源码，仅有 .so + 依赖库）
# ==========================================
FROM python:3.10-slim

WORKDIR /app

# torch 运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ==============================
# Layer 4: Python 依赖（独立缓存）
# ==============================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://download.pytorch.org/whl/cpu

# ==============================
# Layer 5: 模型缓存（独立缓存）
# ==============================
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

# ==============================
# Layer 6: 编译产物 + prompts（改 .py 才重拷）
# ==============================
COPY --from=builder /build/*.so /app/
COPY --from=builder /build/prompts/ /app/prompts/

# 非敏感默认值（密码 / API Key 通过 docker-compose + .env 注入）
ENV ES_URL="http://elasticsearch:9200"
ENV ES_USERNAME="elastic"
ENV ES_VERIFY_CERTS="false"
ENV EMB_MODEL="BAAI/bge-base-zh-v1.5"
ENV EMB_DEVICE="cpu"

EXPOSE 8001

# 生产级 WSGI 服务器
# --preload: 主进程加载模型后 fork worker，copy-on-write 共享内存
# --timeout 150: LLM 调用耗时较长，避免 worker 超时被杀
CMD ["gunicorn", "--preload", "--timeout", "150", "-w", "2", "-b", "0.0.0.0:8001", "api_server:app"]
