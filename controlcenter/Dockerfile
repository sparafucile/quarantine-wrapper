FROM python:3.12-slim

WORKDIR /app

COPY controlcenter/src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY controlcenter/src/ .

# Non-root user
RUN useradd -r -u 1000 cc && chown -R cc:cc /app
USER cc

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"

CMD ["python", "main.py"]
