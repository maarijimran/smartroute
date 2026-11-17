# SmartRoute gateway.
#   docker build -t smartroute-backend .                         # light image, regex detectors only
#   docker build -t smartroute-backend --build-arg INSTALL_ML=true .   # + Presidio, GLiNER, embeddings
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models/huggingface
WORKDIR /srv/backend

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt

ARG INSTALL_ML=false
ARG SPACY_MODEL=en_core_web_lg
# The default Linux PyTorch wheel bundles its CUDA libraries, so the container only
# needs the NVIDIA runtime from the host (see docker-compose.yml).
RUN if [ "$INSTALL_ML" = "true" ]; then \
      pip install torch && pip install -r requirements-ml.txt && python -m spacy download "$SPACY_MODEL"; \
    fi

COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 smartroute \
    && mkdir -p /srv/backend/data /srv/backend/artifacts /models \
    && chown -R smartroute /srv/backend /models
USER smartroute

EXPOSE 8000
# Requests are handled in threads, so one worker serves many concurrent chats.
# The online learner and the rate limiter keep state per process: stay at one worker
# unless you move them to shared storage first.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
