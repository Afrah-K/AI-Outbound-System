"""
Standalone directory/source scrapers.

Each module here pulls a raw lead list (company name, website, location, ...)
from one external source (Clutch, Google Maps, Yelp, ...) and writes it to a
CSV in data/imports/. Not to be confused with app/integrations/scraper, which
finds contact emails for companies already in the database.

Each module can be run three ways:
- As a CLI script: `python scrapers/<source>.py`
- Imported by the FastAPI app's /api/v1/scrapers endpoints (app/routers/scrapers.py),
  so it can be triggered from the frontend's Scrapers page
- Packaged standalone as its own container - see scrapers/clutch_scraper/ for
  the pattern: a Dockerfile + a small interactive entrypoint.py that prompts
  for the scraper's inputs and imports the shared module (e.g. clutch.py)
  rather than duplicating its logic

Pipeline: a scrapers/*.py module -> data/imports/*.csv -> scripts/enrich_csv.py
"""
