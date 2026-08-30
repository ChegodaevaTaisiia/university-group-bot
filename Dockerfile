FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY bot ./bot

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
