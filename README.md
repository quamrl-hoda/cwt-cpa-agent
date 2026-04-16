# CWT CPA Agent — Logistics Cost Intelligence System

A multi-agent Python system that ingests freight/shipping PDFs, extracts cost data,
compares against live market rates (FBX + Xeneta + Shiply), and generates a professional
CPA report with anomaly detection — powered by a Hermes-style tool orchestrator.

Built for: **Crowd Wisdom Trading** internship assessment.



## Architecture — 7 Agents via Hermes Orchestrator

```
PDF Files (local / GDrive / Gmail)
         │
         ▼
┌─────────────────────────────┐
│  HermesOrchestrator         │  core/orchestrator.py
│  (tool registry + pipeline) │  Each agent registered as a named Hermes tool
└────────┬────────────────────┘
         │
         ▼ Tool 1
┌─────────────────────┐
│  Agent 1: Loader    │  Finds & downloads PDFs from chosen source(s)
└────────┬────────────┘
         ▼ Tool 2
┌─────────────────────┐
│  Agent 2: Extractor │  Docling → parse PDF text
│  (Classify + Extract│  LLM → classify type + extract 9 fields
└────────┬────────────┘
         ▼ Tool 3
┌─────────────────────┐
│  Agent 7: Feedback  │  Hermes feedback loop — detects missing fields
│  (Hermes Loop)      │  → re-extracts with improved prompts
│                     │  → saves hints to prompt_memory.json
└────────┬────────────┘
         ▼ Tool 4
┌─────────────────────┐
│  Agent 3: Dedup     │  Prevents duplicate DB records
│  + DB Save          │  Dedup key: shipper + date + cost
└────────┬────────────┘
         ▼ Tool 5
┌─────────────────────┐
│  Agent 4: Calculator│  Avg cost per route, container type,
│                     │  monthly trend, cheapest/most expensive route
└────────┬────────────┘
         ▼ Tool 6
┌─────────────────────┐
│  Agent 5: Freight   │  5-level rate waterfall:
│  Rate Fetcher       │  Shiply(Apify) → FBX Web → Xeneta → FBX API → FBX Static
│                     │  Compares your costs vs market → flags OVERPAYING anomalies
└────────┬────────────┘
         ▼ Tool 7
┌─────────────────────┐
│  Agent 6: Report    │  TXT + HTML CPA report:
│                     │  KPI cards · anomaly cards · LLM executive summary
└─────────────────────┘
         │
         ▼
  outputs/cwt_cpa_report_YYYYMMDD_HHMMSS.txt
  outputs/cwt_cpa_report_YYYYMMDD_HHMMSS.html   ← open in browser
```



## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/cwt-cpa-agent
cd cwt-cpa-agent

# Using uv (recommended)
uv venv
uv pip install -r requirements.txt

# OR using pip
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required:**
- `OPENROUTER_API_KEY` — from https://openrouter.ai/keys (free)
- `LLM_MODEL` — e.g. `openai/gpt-4o-mini` or `google/gemma-3-27b-it:free`

**Optional (market rates):**
- `APIFY_TOKEN` — from https://console.apify.com (Shiply scraper — requires paid plan)
- If no Apify token: system falls back automatically to **FBX Web Scraper → Xeneta → FBX Static**

**Optional (Google integration):**
- `GDRIVE_FOLDER_ID` — Google Drive folder ID (from URL after `/folders/`)
- `GOOGLE_CREDENTIALS_FILE` — path to OAuth2 `credentials.json` from Google Cloud Console
- `GMAIL_SEARCH_QUERY` — custom Gmail search (default: shipping invoices with attachments)

### 3. Add sample PDFs

```bash
# Drop any shipping invoices / freight quotes / bills of lading here:
data/sample_invoices/
```

Sample datasets:
- https://www.kaggle.com/datasets/sanelehlabisa/acclr-dataset
- https://www.kaggle.com/datasets/ayoubcherguelaine/company-documents-dataset

### 4. Run

```bash
# Load from local folder (default — Hermes orchestrator mode)
python main.py

# Load from Google Drive
python main.py --source gdrive

# Load from Gmail attachments
python main.py --source gmail

# Load from BOTH GDrive and Gmail
python main.py --source gdrive,gmail

# All three sources at once
python main.py --source all

# Test pipeline structure without making any API calls
python main.py --dry-run

# Print all registered Hermes tool schemas as JSON
python main.py --list-tools

# Use legacy sequential mode (no orchestrator)
python main.py --legacy
```



## Market Rate Sources (Agent 5 — 5-level waterfall)

| Level | Source | Status |
|-------|--------|--------|
| 1 | **Shiply** via Apify actor `parseforge/shiply-com-freight-marketplace-scraper` | Requires paid Apify plan |
| 2 | **FBX Web Scraper** — live scrape of fbx.freightos.com using beautifulsoup4 | Free, best-effort |
| 3 | **Xeneta Web Scraper** — live scrape of xeneta.com/ocean-freight-rate-indices | Free, best-effort |
| 4 | **FBX REST API** — Freightos Baltic Index public API | Often 403 |
| 5 | **FBX Static Fallback** — hardcoded Q1-2025 reference rates | Always available |



## Output Example

```

          CROWD WISDOM TRADING — CPA Logistics Cost Report        
          Generated: 20250415_143022                              


 SECTION 1: Data Ingestion Summary 
  Total documents processed : 5
  Successfully saved to DB  : 4
  Duplicates skipped        : 1
  Failed / incomplete       : 0

 SECTION 2: Cost Analytics 
  Overall average cost      : $2,145.00
  Average cost per route:
    Shanghai → Rotterdam        $2,300.00
    Shenzhen → Hamburg          $1,890.00
  Monthly trend: ⬆ increasing

  SECTION 3: Market Rate Comparison (Shiply / FBX / Xeneta) 
  Route                               Your Avg     Market      Diff       %    Source
  Shanghai → Rotterdam               $2,300.00  $1,950.00  +$350.00  +17.9%   FBX Web (FBX03)
  Shenzhen → Hamburg                 $1,890.00  $2,100.00  -$210.00  -10.0%   FBX Static (FBX03)

 SECTION 4: Anomalies (1 found) 
  [1] [MEDIUM] OVERPAYING
      Route  : Shanghai → Rotterdam
      Detail : Paying 17.9% above market on Shanghai → Rotterdam.

  SECTION 5: Executive Summary (AI-Generated) 
  The overall average shipping cost of $2,145 is marginally above market...
  Recommendation 1: Renegotiate the Shanghai→Rotterdam contract...
```



## Project Structure

```
cwt-cpa-agent/
├── agents/
│   ├── loader_agent.py       # Agent 1 — PDF loader (local / GDrive / Gmail)
│   ├── extractor_agent.py    # Agent 2 — Docling + LLM classify & extract
│   ├── dedup_agent.py        # Agent 3 — duplicate check + DB save
│   ├── calculator_agent.py   # Agent 4 — cost analytics
│   ├── freight_agent.py      # Agent 5 — live market rates (FBX + Xeneta + Shiply)
│   ├── report_agent.py       # Agent 6 — TXT + HTML CPA report
│   └── feedback_agent.py     # Agent 7 — Hermes feedback/prompt-memory loop
├── core/
│   ├── orchestrator.py       # HermesOrchestrator — tool registry + pipeline runner
│   ├── config.py             # API keys + settings (.env)
│   ├── db.py                 # SQLite helpers (shipments / market_rates / anomalies / logs)
│   ├── llm.py                # OpenRouter wrapper (ask_llm / ask_llm_json)
│   ├── google_auth.py        # OAuth2 for Drive + Gmail
│   └── prompt_memory.json    # Learned extraction hints (written by feedback_agent)
├── data/
│   ├── cwt_shipments.db      # SQLite database
│   └── sample_invoices/      # Drop PDFs here
├── outputs/                  # Reports + log saved here
├── main.py                   # Entry point (Hermes or legacy mode)
├── requirements.txt
├── .env.example
└── README.md
```



## Tech Stack

| Component | Tool |
|-----------|------|
| Agent Framework | Hermes-style tool orchestrator (`core/orchestrator.py`) |
| LLM Provider | OpenRouter — any free model (gpt-4o-mini, gemma, mistral, etc.) |
| PDF Parsing | Docling (primary) + pypdf (fallback) |
| Market Rates | FBX Web Scraper + Xeneta Web Scraper + Shiply/Apify + FBX Static |
| Web Scraping | beautifulsoup4 + lxml |
| Database | SQLite (stdlib — no ORM) |
| Google Integration | Google Drive API v3 + Gmail API v1 (OAuth2) |
| Feedback Loop | Hermes prompt-memory (`core/prompt_memory.json`) |

