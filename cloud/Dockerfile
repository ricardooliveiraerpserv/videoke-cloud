# Imagem da API da nuvem (F2/F3/G1). Enxuta: só kk-shared + kk-core + kk-downloader
# (NÃO inclui o karaokê/PySide6). Build a partir da raiz do repo:
#   docker build -f cloud/Dockerfile -t videoke-cloud .
FROM python:3.12-slim

# uv (gerenciador) a partir da imagem oficial
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY cloud/pyproject.cloud.toml ./pyproject.toml
COPY shared/ ./shared/
COPY library_core/ ./library_core/
COPY downloader/ ./downloader/

# workspace mínimo (sem karaokê/PySide6); puxa fastapi/uvicorn/psycopg/yt-dlp
RUN uv sync --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# Render injeta $PORT; default 8900 local
CMD ["sh", "-c", "uvicorn kk_core.service.asgi:app --host 0.0.0.0 --port ${PORT:-8900}"]
