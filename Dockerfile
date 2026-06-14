FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/hub_tinydb /app/logs && chown -R appuser:appuser /app

USER appuser

EXPOSE 10128

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:10128/health', timeout=3))"

CMD ["python", "hub_server.py"]
