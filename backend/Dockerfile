# Deal Suite API Docker image — one container serving /lbo/* and /ma/*.
# Includes LibreOffice for real workbook recalculation (openpyxl cannot
# compute formulas). Package list carried over from AIO LBO's proven
# Dockerfile — libreoffice-calc + libreoffice-core + headless JRE.

FROM python:3.11-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-core \
        default-jre-headless && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/app

WORKDIR /app

# Requirements first for layer caching. Includes the lazily-imported LLM
# SDKs — their absence from a deployed container silently broke every LLM
# call in AIO LBO.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py entrypoint.sh ./
COPY lbo/ ./lbo/
COPY ma/ ./ma/

RUN chmod +x entrypoint.sh && mkdir -p .sec_cache

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests, os; requests.get(f\"http://localhost:{os.environ.get('PORT', '8000')}/health\")" || exit 1

CMD ["./entrypoint.sh"]
