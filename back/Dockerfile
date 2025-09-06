# ---------- builder: собираем колёса (wheels) ----------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=off \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Системные зависимости для сборки (lxml/cryptography/asyncpg и т.п.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    libpq-dev \
    libssl-dev libffi-dev pkg-config \
    cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Если у вас есть requirements.txt — скопируйте его:
# (используйте тот список, что я дал ранее в ответе)
COPY requirements.txt .

# Соберём колёса заранее — быстрее и повторяемо
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------- runtime: лёгкий рантайм без тулчейна ----------
FROM python:3.11-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Лёгкие рантайм-зависимости (без компилятора)
# libpq5 для asyncpg / psycopg, libssl / libffi — для cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libssl3 libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Установим собранные колёса
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*

# Копируем исходники приложения
WORKDIR /app
COPY . /app

# Необязательно, но полезно: запускаем под непривилегированным пользователем
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# HEALTHCHECK (опционально, если есть /healthz)
# HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
#   CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# Старт сервера
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
