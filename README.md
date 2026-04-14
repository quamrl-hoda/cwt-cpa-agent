# CWT CPA Agent — Logistics Cost Intelligence System

A multi-agent Python system that ingests freight/shipping PDFs, extracts cost data,
compares against live market rates, and generates a professional CPA report with anomaly detection.

Built for: **Crowd Wisdom Trading** internship assessment.

---

## Architecture — 7 Agents

```
PDF Files (local / GDrive / Gmail)
         │
         ▼
┌─────────────────────┐
│  Agent 1: Loader    │  Finds & downloads PDFs from chosen source
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 2: Extractor │  Docling → parse PDF text
│  (Classify + Extract│  LLM → classify type + extract 9 fields
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 7: Feedback  │  Detects missing fields → re-extracts with
│  (Hermes Loop)      │  improved prompts → saves hints to memory
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 3: Dedup     │  Prevents duplicate DB records
│  + DB Save          │  Dedup key: shipper + date + cost
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 4: Calculator│  Avg cost per route, container type,
│                     │  monthly trend, cheapest/most expensive
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 5: Freight   │  Apify → Shiply scraper → live market rates
│  Rate Fetcher       │  Compares your costs vs market → flags anomalies
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Agent 6: Report    │  Generates full CPA report with:
│                     │  cost analytics + anomalies + AI executive summary
└─────────────────────┘
         │
         ▼
  outputs/cwt_cpa_report_YYYYMMDD.txt
```

---

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

Required keys:
- `OPENROUTER_API_KEY` — from https://openrouter.ai/keys (free)
- `APIFY_TOKEN` — from https://console.apify.com (free tier available)

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
# Load from local folder (default)
python main.py

# Load from Google Drive
python main.py --source gdrive

# Load from Gmail attachments
python main.py --source gmail
```

---

## Output Example

```
╔══════════════════════════════════════════════════════════════════╗
║          CROWD WISDOM TRADING — CPA Logistics Cost Report        ║
║          Generated: 20241201_143022                              ║
╚══════════════════════════════════════════════════════════════════╝

━━━ SECTION 1: Data Ingestion Summary ━━━
  Total documents processed : 5
  Successfully saved to DB  : 4
  Duplicates skipped        : 1
  Failed / incomplete       : 0

━━━ SECTION 2: Cost Analytics ━━━
  Overall average cost      : $2,145.00
  Average cost per route:
    Shanghai → Rotterdam        $2,300.00
    Shenzhen → Hamburg          $1,890.00
  Monthly trend: ⬆ increasing

━━━ SECTION 3: Market Rate Comparison ━━━
  Route                               Your Avg     Market      Diff       %
  Shanghai → Rotterdam               $2,300.00  $1,950.00  +$350.00  +17.9%
  Shenzhen → Hamburg                 $1,890.00  $2,100.00  -$210.00  -10.0%

━━━ SECTION 4: Anomalies (1 found) ━━━
  [1] OVERPAYING
      Route:   Shanghai → Rotterdam
      Detail:  You are paying 17.9% above market rate...

━━━ SECTION 5: Executive Summary (AI-Generated) ━━━
  The overall average shipping cost of $2,145 is marginally above market...
  Recommendation 1: Renegotiate the Shanghai→Rotterdam contract...
```

---

## Project Structure

```
cwt-cpa-agent/
├── agents/
│   ├── loader_agent.py       # Agent 1
│   ├── extractor_agent.py    # Agent 2
│   ├── dedup_agent.py        # Agent 3
│   ├── calculator_agent.py   # Agent 4
│   ├── freight_agent.py      # Agent 5
│   ├── report_agent.py       # Agent 6
│   └── feedback_agent.py     # Agent 7
├── core/
│   ├── config.py             # API keys + settings
│   ├── db.py                 # SQLite helpers
│   └── llm.py                # OpenRouter wrapper
├── data/
│   └── sample_invoices/      # Drop PDFs here
├── outputs/                  # Reports saved here
├── main.py                   # Orchestrator
├── requirements.txt
├── .env.example
└── README.md
```

---

## Tech Stack

| Component | Tool |
|-----------|------|
| LLM | OpenRouter (any free model) |
| PDF Parsing | Docling + pypdf fallback |
| Market Rates | Apify — parseforge/shiply-com-freight-marketplace-scraper |
| Database | SQLite (via Python stdlib) |
| Google Integration | Google Drive API + Gmail API |
| Feedback Loop | Hermes-style prompt memory (prompt_memory.json) |

---

## Submission

- GitHub: [your repo link]
- Apify token: [submit in email as required]
- Output examples: see `outputs/` folder

Submit to: gilad@crowdwisdomtrading.com
=======
# cwt-cpa-agent
Multi-agent AI system for logistics cost analysis using OCR, LLMs, and real-time market data.