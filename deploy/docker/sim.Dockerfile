# The simulated model (development, tests and demos only; never deployed next to patient data).
FROM python:3.12.8-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 CTA_ROOT=/app
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-compile . && useradd --system --uid 10001 sim
COPY config/ config/
USER 10001
EXPOSE 8071
CMD ["ctasim", "serve-model", "--host", "0.0.0.0", "--port", "8071"]
