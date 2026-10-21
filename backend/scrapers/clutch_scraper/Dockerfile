# Containerized Clutch scraper - interactive CLI (asks for a category and
# page count), using the same Playwright-based live scraper as the app.
#
# Build context must be backend/ (this Dockerfile needs scrapers/clutch.py):
#   docker build -f scrapers/clutch_scraper/Dockerfile -t clutch-scraper .
#
# Run (mount a host folder so the output CSV survives the container):
#   docker run -it -v "$(pwd)/data/imports:/data" clutch-scraper
#
# Runs headed (visible-window) Chromium under Xvfb's virtual display, since
# Clutch's Cloudflare check blocks headless Chromium specifically - see
# scrapers/clutch.py's module docstring for why.

FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir beautifulsoup4==4.12.3 lxml==5.1.0

COPY scrapers/__init__.py ./scrapers/__init__.py
COPY scrapers/clutch.py ./scrapers/clutch.py
COPY scrapers/clutch_scraper/entrypoint.py ./entrypoint.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["xvfb-run", "-a", "python", "entrypoint.py"]
