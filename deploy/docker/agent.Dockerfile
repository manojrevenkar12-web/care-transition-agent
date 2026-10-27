# The platform: API and clinician console. Build from the repository root:
#   docker build -f deploy/docker/agent.Dockerfile -t cta-agent .
FROM node:22.11-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.8-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 CTA_ROOT=/app
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-compile . && useradd --system --uid 10001 cta
COPY config/ config/
COPY prompts/ prompts/
COPY reports/ reports/
COPY --from=web /web/dist web/dist
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["cta", "serve", "--host", "0.0.0.0", "--port", "8000"]
