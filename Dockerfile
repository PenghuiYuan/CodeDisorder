# syntax=docker/dockerfile:1.6
# Multi-stage build: build the React frontend, then drop it into the API image
# which also serves it as static files.

# -------- Stage 1: build the React frontend --------
FROM node:20-alpine AS web-build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build        # → /web/dist


# -------- Stage 2: API runtime (Python + libclang) --------
FROM python:3.11-slim AS api

# Tools we need:
#   * build-essential  — fallback gcc/g++ in case clang is missing
#   * clang            — verify step (DESIGN §9.1)
#   * libclang-dev     — PyClang C bindings need both headers and the .so
#   * wamerican        — provides /usr/share/dict/words for gen_wordlist.py
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        clang \
        libclang-dev \
        wamerican \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy the backend
COPY backend/ ./backend/

# Generate the wordlist in the image (replaces the .gitignored
# backend/resources/wordlist.txt at build time)
RUN python -m backend.tools.gen_wordlist \
        --src /usr/share/dict/words \
        --out backend/resources/wordlist.txt \
 && ls -la backend/resources/wordlist.txt

# Copy the built frontend into the image. main.py mounts /app/frontend/dist
# as static at "/" — see backend/api/main.py for the StaticFiles config.
COPY --from=web-build /web/dist ./frontend/dist

# Where the bundled libclang lives on Debian 12 (bookworm) — exposed via env
# so PyClang can find it without us hard-coding in code.
ENV LIBCLANG_LIBRARY_PATH=/usr/lib/llvm-14/lib/libclang.so.1
ENV WORKER_MODE=stdio
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Healthcheck: 1s delay, 5s period, 3 retries, 3s timeout. uvicorn boots in
# well under 1s on a warm container, so we give it a moment.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 --start-period=5s \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status == 200 else sys.exit(1)"

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
