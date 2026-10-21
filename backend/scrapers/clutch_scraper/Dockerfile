# Containerized Clutch scraper - interactive CLI (asks for a category and
# page count), using the same Playwright-based live scraper as the app.
#
# Build context must be backend/ (this Dockerfile needs scrapers/clutch.py):
#   docker build -f scrapers/clutch_scraper/Dockerfile -t clutch-scraper .
#
# Run (mount a host folder so the output CSV survives the container):
#   docker run -it -v "$(pwd)/data/imports:/data" clutch-scraper
#
# Runs the full Chromium build headless (no display needed) - see
# scrapers/clutch.py's module docstring for why it's not the headless shell.

FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

RUN pip install --no-cache-dir beautifulsoup4==4.12.3 lxml==5.1.0

COPY scrapers/__init__.py ./scrapers/__init__.py
COPY scrapers/clutch.py ./scrapers/clutch.py
COPY scrapers/clutch_scraper/entrypoint.py ./entrypoint.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "entrypoint.py"]
