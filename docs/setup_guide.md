# Setup Guide

Complete installation, configuration, and run guide for CWT CPA Agent.


## Prerequisites

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.11+ | Uses `list[str]` generics, `str \| None` union syntax |
| pip / uv | latest | `uv` recommended for faster installs |
| OpenRouter API key | — | Free at https://openrouter.ai/keys |
| PDFs | — | Drop into `data/sample_invoices/` |


## 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/cwt-cpa-agent
cd cwt-cpa-agent
```

---

## 2. Create a Virtual Environment

### Using `uv` (recommended)

```bash
# Install uv if you don't have it
pip install uv

# Create venv and install dependencies
uv venv
uv pip install -r requirements.txt
```

### Using standard `pip`

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in the required values:

### Required

```dotenv
# OpenRouter API key — free at https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-...

# LLM model identifier (any OpenRouter-supported model)
# Free options:
LLM_MODEL=openai/gpt-4o-mini
# LLM_MODEL=google/gemma-3-27b-it:free
# LLM_MODEL=mistralai/mistral-7b-instruct:free
```

### Optional — Market Rates (Shiply via Apify)

```dotenv
# Only needed for Level 1 rate source (Shiply marketplace)
# Requires a paid Apify plan — system falls back automatically without this
APIFY_TOKEN=apify_api_...
```

### Optional — Google Drive Integration

```dotenv
# Paste the folder ID from your Drive URL:
# https://drive.google.com/drive/folders/THIS_PART_HERE
GDRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrSt

# Path to your downloaded OAuth2 credentials file
GOOGLE_CREDENTIALS_FILE=credentials.json

# Set to false to only scan the top-level Drive folder
GDRIVE_RECURSIVE=true
```

### Optional — Gmail Integration

```dotenv
# Gmail search query (see https://support.google.com/mail/answer/7190)
GMAIL_SEARCH_QUERY=subject:(invoice OR freight OR shipping OR bill of lading) has:attachment

# Maximum number of emails to scan
GMAIL_MAX_RESULTS=30
```

### Optional — Advanced

```dotenv
# Database location
DB_PATH=data/cwt_shipments.db

# Anomaly threshold — flag as OVERPAYING if cost is X% above market
ANOMALY_THRESHOLD_PCT=20

# Report output format: txt | html | txt,html
REPORT_FORMAT=txt
```

---

## 4. Add PDF Documents

Drop any shipping-related PDF files into:

```
data/sample_invoices/
```

Supported document types:
- **Invoices** — commercial, freight, or shipping invoices
- **Bills of Lading** — ocean or multimodal B/L
- **Freight Quotes** — carrier quotes or spot rate sheets
- **Customs Documents** — import/export declarations

> **Note:** Non-logistics documents (product catalogues, general invoices, etc.) are automatically classified as `"unknown"` and skipped — no extraction is attempted.

### Sample Datasets

If you don't have your own documents, these Kaggle datasets work well:
- https://www.kaggle.com/datasets/sanelehlabisa/acclr-dataset
- https://www.kaggle.com/datasets/ayoubcherguelaine/company-documents-dataset

---

## 5. (Optional) Set Up Google Integration

### Google Drive

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Drive API**
3. Go to **APIs & Services → Credentials → Create OAuth 2.0 Client ID**
4. Application type: **Desktop app**
5. Download the JSON file and save it as `credentials.json` in the project root
6. Set `GDRIVE_FOLDER_ID` in your `.env` to the target folder ID from the Drive URL

On first run with `--source gdrive`, a browser window will open for consent. The token is cached in `token_drive.json` for subsequent runs.

### Gmail

Uses the same `credentials.json` file. Enable the **Gmail API** in the same Google Cloud project.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **Gmail API** (same project)
3. On first run with `--source gmail`, a browser window will open for consent
4. Token cached in `token_gmail.json`

---

## 6. Run the Pipeline

### Basic run (local PDFs, Hermes orchestrator)

```bash
python main.py
```

### All run options

```bash
# Local PDFs (default)
python main.py

# Google Drive folder
python main.py --source gdrive

# Gmail attachments
python main.py --source gmail

# Both Drive and Gmail (combined, deduplicated)
python main.py --source gdrive,gmail

# All three sources
python main.py --source all

# Test pipeline structure — no API calls, no LLM, no downloads
python main.py --dry-run

# Print all Hermes tool schemas as JSON and exit
python main.py --list-tools

# Legacy sequential mode (bypasses orchestrator — for debugging)
python main.py --legacy
```

---

## 7. View Output

Reports are saved in the `outputs/` directory:

```
outputs/
├── cwt_cpa_report_20250415_143022.txt     ← plain text report
└── cwt_agent.log                          ← full pipeline log
```

The report contains 9 sections covering ingestion summary, cost analytics, market comparisons, anomalies, and an LLM-generated executive summary.

---

## Troubleshooting

### `OPENROUTER_API_KEY is not set`

Set `OPENROUTER_API_KEY` in your `.env` file. Get a free key at https://openrouter.ai/keys.

### `No PDFs found`

Ensure at least one `.pdf` file exists in `data/sample_invoices/`. The directory is created automatically on startup if missing.

### `Extraction returned no records`

All PDFs were classified as `"unknown"` (non-logistics documents). Check that your files are actual shipping invoices, bills of lading, or freight quotes.

### LLM returns empty or error responses

Try a different model. Set `LLM_MODEL=google/gemma-3-27b-it:free` in `.env` for a reliable free alternative.

### Google Drive / Gmail: `credentials.json not found`

Download your OAuth2 credentials from Google Cloud Console and place the file in the project root as `credentials.json`. Set `GOOGLE_CREDENTIALS_FILE=credentials.json` (or the full path) in `.env`.

### Google auth: `token_drive.json` invalid

Delete `token_drive.json` (or `token_gmail.json`) and re-authenticate by running with `--source gdrive` (or `--source gmail`) again.

### `sqlite3.OperationalError: no such column: rate_source`

Run the pipeline once — `init_db()` applies schema migrations automatically on startup.

### Windows encoding error (arrows `→`, `⬆` in log)

This is handled automatically. `main.py` calls `sys.stdout.reconfigure(encoding="utf-8")` at startup. If you still see errors, run:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python main.py
```

---

## Dependencies

```
python-dotenv       # .env loading
requests            # OpenRouter HTTP calls
docling             # Primary PDF parser
pypdf               # Fallback PDF parser
google-api-python-client  # Drive + Gmail API
google-auth
google-auth-oauthlib
google-auth-httplib2
apify-client        # Shiply market rate scraper
beautifulsoup4      # FBX / Xeneta web scraping
lxml                # HTML parsing backend
```

All are installed by `pip install -r requirements.txt`.
