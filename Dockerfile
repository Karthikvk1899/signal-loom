FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
COPY loom ./loom
RUN pip install -r requirements.lock && pip install --no-deps . && useradd --uid 10001 --create-home loom
COPY tests ./tests
COPY scripts ./scripts
USER 10001
EXPOSE 8080
CMD ["uvicorn", "loom.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
