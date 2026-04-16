# Agents Reference

All 7 agents live in the `agents/` package. Each exposes a single public `run()` function and is registered as a **Hermes tool** in `core/orchestrator.py`.

---

## Agent 1 — Loader Agent

**File:** `agents/loader_agent.py`  
**Tool name:** `loader`  
**Hermes step:** 1

### Purpose

Discovers and downloads PDF files from one of three sources: the local file system, Google Drive, or Gmail attachments. Returns a deduplicated list of local file paths ready for extraction.

### Public API

```python
def run(source: str = "local") -> list[str]
```

| Parameter | Type | Values | Default |
|---|---|---|---|
| `source` | `str` | `"local"` \| `"gdrive"` \| `"gmail"` | `"local"` |

**Returns:** `list[str]` — absolute or relative paths to PDF files on disk.

### Source Behaviour

#### `"local"`
- Recursively scans `data/sample_invoices/` (configurable via `SAMPLE_PDF_DIR`)
- Creates the directory if it doesn't exist
- Returns all `*.pdf` paths sorted alphabetically

#### `"gdrive"`
- Authenticates via OAuth2 (browser popup on first run; token cached in `token_drive.json`)
- Requires `GDRIVE_FOLDER_ID` in `.env`
- Downloads native PDFs and exports Google Docs/Sheets/Slides as PDF
- Skips already-downloaded files (by filename)
- If `GDRIVE_RECURSIVE=true`, scans sub-folders recursively
- Downloads saved to `data/sample_invoices/gdrive_downloads/`

#### `"gmail"`
- Authenticates via OAuth2 (browser popup on first run; token cached in `token_gmail.json`)
- Searches Gmail using `GMAIL_SEARCH_QUERY` (default: shipping/invoice/freight subjects with attachments)
- Downloads up to `GMAIL_MAX_RESULTS` messages (default: 30)
- Deduplicates by Gmail message ID
- Downloads saved to `data/sample_invoices/gmail_downloads/`

### Logging

Writes a `success` or `failure` entry to the `agent_logs` table via `log_agent()`.

---

## Agent 2 — Extractor Agent

**File:** `agents/extractor_agent.py`  
**Tool name:** `extractor`  
**Hermes step:** 2

### Purpose

Processes each PDF through a 4-step pipeline: parse → classify → extract → normalise. Uses Docling for high-quality PDF parsing with pypdf as fallback.

### Public API

```python
def run(pdf_paths: list[str]) -> list[dict]
```

**Returns:** `list[dict]` — one dict per PDF with 9 extracted fields + metadata.

### Extracted Fields

| Field | Type | Aliases Searched |
|---|---|---|
| `shipper` | `str \| None` | From, Seller, Vendor, Supplier, Exporter, Consignor |
| `consignee` | `str \| None` | To, Buyer, Customer, Ship To, Bill To, Importer |
| `origin_port` | `str \| None` | Port of Loading, POL, From Port, Departure Port |
| `destination_port` | `str \| None` | Port of Discharge, POD, To Port, Final Destination |
| `container_type` | `str \| None` | 20ft, 40ft, LCL, FCL, TEU, Container Size |
| `weight_kg` | `float \| None` | Weight, Gross Weight (lbs auto-converted) |
| `total_cost` | `float \| None` | Total, Amount Due, Grand Total, Freight Charges |
| `currency` | `str \| None` | ISO code: USD, GBP, EUR, JPY ($ → USD, £ → GBP) |
| `invoice_date` | `str \| None` | Date, Invoice Date, Issue Date (YYYY-MM-DD format) |

**Metadata added:**
- `doc_type` — classified document type
- `source_file` — original file path
- `skip_reason` — explanation if document was skipped

### Document Types

```python
DOC_TYPES = ["invoice", "bill_of_lading", "freight_quote", "customs_doc", "unknown"]
```

Documents classified as `"unknown"` are skipped (not sent to the LLM extractor). A shell record with all-`None` fields is returned so downstream agents know the file was seen.

### Internal Steps

#### Step 1 — PDF Parsing (`_parse_pdf`)
- Tries **Docling** first (`DocumentConverter` → `export_to_markdown()`)
- Falls back to **pypdf** if Docling is not installed
- Returns empty string on failure

#### Step 2 — Classification (`_classify`)
- Sends first 1,500 characters to LLM with `temperature=0.0`
- Validates response against `DOC_TYPES`
- Returns `"unknown"` for any unrecognised label

#### Step 3 — Field Extraction (`_extract`)
- Loads any saved prompt hints from `core/prompt_memory.json` for the doc type
- Builds a detailed extraction prompt with field aliases
- Sends up to 4,000 characters of document text
- Parses JSON response and normalises types (`total_cost`/`weight_kg` → `float`)

#### Step 4 — Post-processing
- **Currency heuristic** (`_infer_currency`): scans first 2,000 chars for `$`, `£`, `€`, `¥`
- **Destination fallback** (`_infer_destination_from_consignee`): if `destination_port` is still `None`, runs a targeted LLM call focused on the consignee address block

### Prompt Memory

On each run, `_load_prompt_hints(doc_type)` reads `core/prompt_memory.json` and appends any saved hints to the extraction prompt. Hints are written by `feedback_agent` when re-extraction succeeds.

---

## Agent 3 — Dedup Agent

**File:** `agents/dedup_agent.py`  
**Tool name:** `dedup`  
**Hermes step:** 4

### Purpose

Prevents duplicate records in the SQLite database. Checks each extracted (and feedback-improved) record against existing rows before inserting.

### Public API

```python
def run(extracted_records: list[dict]) -> dict
```

**Returns:**

```python
{
    "total_input":    int,
    "saved":          int,
    "skipped":        int,
    "failed":         int,
    "saved_records":  [{"id": int, "file": str}, ...],
    "skipped_files":  [str, ...],
    "failed_records": [{"file": str, "reason": str}, ...],
}
```

### Deduplication Logic

**Dedup key:** `(normalised_shipper, invoice_date, total_cost)`

- `shipper` is normalised: `None` and whitespace-only values all map to `""` so that inconsistent extraction across retries doesn't create phantom duplicates
- Also matches rows where `shipper IS NULL` to handle pre-normalisation DB rows
- `total_cost` is matched exactly (float equality)

### Skip Conditions

A record is skipped (counted as `failed`) — not as a duplicate — when:
1. `doc_type == "unknown"` or `skip_reason` is present (rejected by extractor)
2. `total_cost` is `None` (minimum required field for dedup key)

---

## Agent 4 — Calculator Agent

**File:** `agents/calculator_agent.py`  
**Tool name:** `calculator`  
**Hermes step:** 5

### Purpose

Reads all shipment records from the database and computes shipping cost analytics used by the report and freight agents.

### Public API

```python
def run() -> dict
```

**Returns:**

```python
{
    "total_shipments":        int,
    "valid_for_calc":         int,
    "overall_avg_cost":       float,
    "avg_cost_per_route":     {"{origin} → {dest}": float, ...},
    "avg_cost_per_container": {"20ft": float, "lcl": float, ...},
    "most_expensive_route":   {"route": str, "avg_cost_usd": float},
    "cheapest_route":         {"route": str, "avg_cost_usd": float},
    "monthly_trend":          {
        "by_month":         {"YYYY-MM": float, ...},
        "trend_direction":  "⬆ increasing" | "⬇ decreasing" | "→ stable"
    }
}
```

Returns `{"error": "No shipments found in DB"}` if the DB is empty.

### Analytics Functions

| Function | Description |
|---|---|
| `_overall_avg` | Sum of all costs / count |
| `_avg_by_route` | Groups by `"{origin_port} → {destination_port}"` |
| `_avg_by_container` | Groups by `container_type` (lowercased) |
| `_extremes(mode="max"\|"min")` | Most/cheapest route from per-route averages |
| `_monthly_trend` | Averages by `YYYY-MM`, adds direction label comparing last two months |

---

## Agent 5 — Freight Agent

**File:** `agents/freight_agent.py`  
**Tool name:** `freight`  
**Hermes step:** 6

### Purpose

Fetches current ocean freight market rates and compares them against your actual costs. Flags routes where you are overpaying above the anomaly threshold (default: 20%).

### Public API

```python
def run(calc_results: dict) -> dict
```

**Returns:**

```python
{
    "fbx_rates":   {"FBX01": float, "FBX03": float, ...},
    "comparisons": [
        {
            "route":        str,
            "your_avg_usd": float,
            "market_rate":  float | None,
            "difference":   float | None,
            "pct_diff":     float | None,
            "overpaying":   bool,
            "rate_source":  str,
        },
        ...
    ],
    "anomalies": [
        {
            "type":     "OVERPAYING" | "UNDERPAYING",
            "severity": "HIGH" | "MEDIUM" | "LOW",
            "route":    str,
            "your_avg": float,
            "market_rate": float,
            "pct_diff": float,
            "message":  str,
        },
        ...
    ]
}
```

### Rate Source Waterfall

```
Level 1  Shiply (Apify actor)       requires APIFY_TOKEN + paid plan
Level 2  FBX Web Scraper            live scrape of fbx.freightos.com
Level 3  Xeneta Web Scraper         live scrape of xeneta.com/ocean-freight-rate-indices  
Level 4  FBX REST API               GET https://fbx.freightos.com/api/v1/rates
Level 5  FBX Static Fallback        hardcoded Q1-2025 corridor benchmarks
```

### FBX Static Corridors

| Index | Route Corridor |
|---|---|
| FBX01 | China / East Asia → US West Coast |
| FBX02 | China / East Asia → US East Coast |
| FBX03 | China / East Asia → North Europe |
| FBX04 | China / East Asia → Mediterranean |
| FBX11 | US West Coast → China / East Asia |
| FBX13 | N. Europe → China / East Asia |

### Anomaly Detection

A comparison is flagged as `OVERPAYING` when:
- `pct_diff > ANOMALY_THRESHOLD_PCT` (default: 20%)
- Severity is `HIGH` if `pct_diff > 40%`, else `MEDIUM`

Anomalies are also written to the `anomalies` table in SQLite via `insert_anomaly()`.

---

## Agent 6 — Report Agent

**File:** `agents/report_agent.py`  
**Tool name:** `report`  
**Hermes step:** 7

### Purpose

Generates the final CPA report. Produces a plain-text (`.txt`) report and optionally an HTML version. The report includes 6 sections plus an AI-generated executive summary.

### Public API

```python
def run(
    dedup_summary:   dict,
    calc_results:    dict,
    freight_results: dict,
) -> str
```

**Returns:** `str` — path to the saved TXT report file.

### Report Sections

| Section | Content |
|---|---|
| Header | Timestamp, company name |
| Multi-Agent Pipeline | Architecture table showing all 7 agents and their roles |
| Document Classification | Breakdown from extractor_agent logs (success / skipped / failed) |
| Data Ingestion | Documents processed, saved, duplicates, failures |
| Cost Analytics | Overall avg, per-route table, monthly trend |
| Market Comparison | Your cost vs market rate, diff %, source, anomaly flags |
| Anomalies | Detailed anomaly cards with severity, route, and message |
| Feedback Loop | Fields recovered by re-extraction, prompt memory status |
| Executive Summary | AI-generated 150–250 word board-level summary |

### Executive Summary Prompt

The LLM is prompted as a *senior CPA specialising in international logistics cost control* to produce a board-level summary covering:
1. Overall cost performance
2. Top 1–2 anomalies and financial impact
3. Market rate context (data sources used)
4. 3 concrete cost-reduction recommendations

---

## Agent 7 — Feedback Agent

**File:** `agents/feedback_agent.py`  
**Tool name:** `feedback`  
**Hermes step:** 3 (runs immediately after extraction)

### Purpose

Implements the **Hermes feedback loop**: detects incomplete extraction results, re-extracts missing fields with improved targeted prompts, and persists successful hint patterns for future runs.

### Public API

```python
def run(
    extracted_records: list[dict],
    raw_texts: dict[str, str],
) -> list[dict]
```

| Parameter | Description |
|---|---|
| `extracted_records` | Output from `extractor_agent.run()` |
| `raw_texts` | Dict mapping `source_file → raw PDF text` (avoids re-parsing) |

**Returns:** Same shape as input — improved records replace originals.

### Critical Fields Monitored

```python
CRITICAL_FIELDS = ["shipper", "total_cost", "origin_port", "destination_port", "invoice_date"]
```

### Feedback Loop Steps

1. **Scan** each record for `None` or `""` critical fields
2. **Skip** documents with `doc_type == "unknown"` or `skip_reason` set
3. **Build targeted prompt** showing the model what was already extracted and asking only for the missing fields with alias hints
4. **Merge** successfully recovered values into the original record
5. **Save hints** to `core/prompt_memory.json` when recovery succeeds

### Prompt Memory Format

```json
{
  "invoice": [
    "Field 'destination_port' may require alias lookup (was missing in initial pass)",
    "Field 'shipper' may require alias lookup (was missing in initial pass)"
  ],
  "freight_quote": [
    "Field 'invoice_date' may require alias lookup (was missing in initial pass)"
  ]
}
```

Hints accumulate over time. Future runs of `extractor_agent` prepend these hints to the main extraction prompt, improving first-pass accuracy.
