FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

COPY config/settings.toml config/settings.toml

EXPOSE 8080

CMD ["python", "-m", "scalpy.main"]
