# Configuration Reference

Complete reference for all environment variables and configuration constants in CWT CPA Agent.

---

## Environment Variables (`.env`)

All variables are loaded from `.env` via `python-dotenv` in `core/config.py`.

Copy `.env.example` as the starting point:

```bash
cp .env.example .env
```

---

## LLM Provider

### `OPENROUTER_API_KEY`

| | |
|---|---|
| **Required** | Yes |
| **Default** | `""` (raises `EnvironmentError` at runtime if empty) |

Your OpenRouter API key. Get one free at https://openrouter.ai/keys.

```dotenv
OPENROUTER_API_KEY=sk-or-v1-abc123...
```

---

### `LLM_MODEL`

| | |
|---|---|
| **Required** | No |
| **Default** | `openai/gpt-4o-mini` |

The model identifier to use for all LLM calls (classification, extraction, executive summary). Any model available on OpenRouter is valid.

```dotenv
LLM_MODEL=openai/gpt-4o-mini
```

**Recommended free models:**

| Model | Speed | Quality | Notes |
|---|---|---|---|
| `openai/gpt-4o-mini` | Fast | High | Best overall for extraction |
| `google/gemma-3-27b-it:free` | Med | High | Good JSON compliance |
| `mistralai/mistral-7b-instruct:free` | Fast | Medium | Lightweight fallback |

**Temperature used per task:**

| Task | Temperature | `max_tokens` |
|---|---|---|
| Document classification | 0.0 | 20 |
| Field extraction (JSON) | 0.1 | 1500 |
| Destination inference | 0.0 | 30 |
| Feedback re-extraction | 0.1 | 1500 |
| Executive summary | 0.3 | 500 |

---

## Market Rate Sources

### `APIFY_TOKEN`

| | |
|---|---|
| **Required** | No |
| **Default** | `""` |

Apify API token for Shiply marketplace scraping (Level 1 in the rate waterfall). Requires a **paid Apify plan**. The system falls back automatically to FBX Web Scraper (Level 2) if this is not set.

```dotenv
APIFY_TOKEN=apify_api_xyz789...
```

---

### `SHIPLY_ACTOR_ID`

| | |
|---|---|
| **Required** | No |
| **Default** | `parseforge/shiply-com-freight-marketplace-scraper` |

The Apify actor ID for Shiply scraping. Change only if using a custom actor.

```dotenv
SHIPLY_ACTOR_ID=parseforge/shiply-com-freight-marketplace-scraper
```

---

## Google Integration

### `GOOGLE_CREDENTIALS_FILE`

| | |
|---|---|
| **Required** | Only for `gdrive` or `gmail` sources |
| **Default** | `credentials.json` |

Path to the OAuth2 credentials JSON file downloaded from Google Cloud Console.

```dotenv
GOOGLE_CREDENTIALS_FILE=credentials.json
# Or a full path:
GOOGLE_CREDENTIALS_FILE=C:/Users/you/keys/google-oauth.json
```

---

### `GDRIVE_FOLDER_ID`

| | |
|---|---|
| **Required** | Only for `--source gdrive` |
| **Default** | `""` (logs error and returns empty list) |

The ID of the Google Drive folder to scan for PDFs. Find it in the Drive URL:

```
https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWx
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        This is the folder ID
```

```dotenv
GDRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWx
```

---

### `GDRIVE_RECURSIVE`

| | |
|---|---|
| **Required** | No |
| **Default** | `true` |
| **Values** | `true` \| `false` (case-insensitive) |

Whether to recursively scan sub-folders inside the target Google Drive folder.

```dotenv
GDRIVE_RECURSIVE=true
```

---

### `GMAIL_SEARCH_QUERY`

| | |
|---|---|
| **Required** | No |
| **Default** | `subject:(invoice OR freight OR shipping OR bill of lading) has:attachment` |

Gmail search query used to find relevant emails with PDF attachments. Follows Gmail search operators (see https://support.google.com/mail/answer/7190).

```dotenv
GMAIL_SEARCH_QUERY=subject:(invoice OR freight OR shipping OR bill of lading) has:attachment

# Narrow to specific sender
GMAIL_SEARCH_QUERY=from:carrier@example.com has:attachment filename:pdf

# Search by date range
GMAIL_SEARCH_QUERY=subject:(invoice) has:attachment after:2025/01/01
```

---

### `GMAIL_MAX_RESULTS`

| | |
|---|---|
| **Required** | No |
| **Default** | `30` |
| **Type** | `int` |

Maximum number of Gmail messages to scan for PDF attachments.

```dotenv
GMAIL_MAX_RESULTS=50
```

---

## Storage Paths

### `DB_PATH`

| | |
|---|---|
| **Required** | No |
| **Default** | `data/cwt_shipments.db` |

Path to the SQLite database file. Parent directories are created automatically.

```dotenv
DB_PATH=data/cwt_shipments.db
```

---

## Budget / Thresholds

### `ANOMALY_THRESHOLD_PCT`

| | |
|---|---|
| **Required** | No |
| **Default** | `20` |
| **Type** | `int` (percentage) |

The percentage above market rate at which a route is flagged as an `OVERPAYING` anomaly. For example, with the default of `20`, a route that costs 21% above market will be flagged.

Severity is additional:
- `> 40%` → `HIGH`
- `> 20%` (threshold) → `MEDIUM`

```dotenv
ANOMALY_THRESHOLD_PCT=20
```

---

### `REPORT_FORMAT`

| | |
|---|---|
| **Required** | No |
| **Default** | `txt` |
| **Values** | `txt` \| `html` \| `txt,html` |

Output format for generated reports. `txt,html` generates both simultaneously.

```dotenv
REPORT_FORMAT=txt
# REPORT_FORMAT=txt,html
```

---

## Hardcoded Constants (not env vars)

These are defined directly in `core/config.py` and are not overridable via `.env`:

| Constant | Value | Description |
|---|---|---|
| `SAMPLE_PDF_DIR` | `"data/sample_invoices"` | Local PDF input folder |
| `OUTPUT_DIR` | `"outputs"` | Report output folder |
| `PROMPT_MEMORY` | `"core/prompt_memory.json"` | Feedback hints file |
| `OPENROUTER_BASE_URL` | `"https://openrouter.ai/api/v1/chat/completions"` | API endpoint |

---

## LLM Retry Constants (in `core/llm.py`)

| Constant | Value | Description |
|---|---|---|
| `_MAX_RETRIES` | `3` | Max retry attempts per LLM call |
| `_RETRY_BACKOFF` | `2.0` | Base backoff in seconds (doubles each retry: 2s → 4s → 8s) |

These are not exposed as environment variables. Edit `core/llm.py` directly to change them.

---

## Full `.env.example`

```dotenv
# ─── Required ───────────────────────────────────────────────
OPENROUTER_API_KEY=sk-or-v1-...
LLM_MODEL=openai/gpt-4o-mini

# ─── Optional: Market Rates (Shiply via Apify) ──────────────
# Requires a paid Apify plan. System falls back to FBX if not set.
APIFY_TOKEN=apify_api_...
SHIPLY_ACTOR_ID=parseforge/shiply-com-freight-marketplace-scraper

# ─── Optional: Google Drive ──────────────────────────────────
GOOGLE_CREDENTIALS_FILE=credentials.json
GDRIVE_FOLDER_ID=
GDRIVE_RECURSIVE=true

# ─── Optional: Gmail ─────────────────────────────────────────
GMAIL_SEARCH_QUERY=subject:(invoice OR freight OR shipping OR bill of lading) has:attachment
GMAIL_MAX_RESULTS=30

# ─── Optional: Storage & Thresholds ─────────────────────────
DB_PATH=data/cwt_shipments.db
ANOMALY_THRESHOLD_PCT=20
REPORT_FORMAT=txt
```
