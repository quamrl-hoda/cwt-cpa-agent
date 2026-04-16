# Data Flow

End-to-end walkthrough of the CWT CPA Agent pipeline — what data looks like at each step.

---

## Overview

```
[PDF Files]
     │
     ▼  Step 1: loader
[list[str]]  ← file paths
     │
     ▼  Step 2: extractor
[list[dict]] ← 9-field records (one per PDF)
     │
     ▼  Step 3: feedback (Hermes loop)
[list[dict]] ← same shape, missing fields filled
     │
     ▼  Step 4: dedup + DB write
[dict]       ← summary (saved / skipped / failed)
     │
     ▼  Step 5: calculator
[dict]       ← avg costs, routes, trend
     │
     ▼  Step 6: freight
[dict]       ← market rates, comparisons, anomalies
     │
     ▼  Step 7: report
[str]        ← path to TXT report file
```

---

## Step 1 — Loader Output

`loader_agent.run(source="local")` returns a flat list of file paths:

```python
[
    "data/sample_invoices/invoice_001.pdf",
    "data/sample_invoices/invoice_002.pdf",
    "data/sample_invoices/gdrive_downloads/freight_quote.pdf",
]
```

When multiple sources are used, the orchestrator calls the loader once per source and merges results by path (deduplication via a `set`).

---

## Step 2 — Extractor Output

`extractor_agent.run(pdf_paths)` returns one dict per PDF:

### Successful extraction

```python
{
    "shipper":          "Maersk Line Ltd",
    "consignee":        "Global Imports GmbH",
    "origin_port":      "Shanghai",
    "destination_port": "Rotterdam",
    "container_type":   "40ft",
    "weight_kg":        12500.0,
    "total_cost":       2300.00,
    "currency":         "USD",
    "invoice_date":     "2025-01-15",
    "doc_type":         "invoice",
    "source_file":      "data/sample_invoices/invoice_001.pdf",
}
```

### Skipped document (classified as `"unknown"`)

```python
{
    "shipper":          None,
    "consignee":        None,
    "origin_port":      None,
    "destination_port": None,
    "container_type":   None,
    "weight_kg":        None,
    "total_cost":       None,
    "currency":         None,
    "invoice_date":     None,
    "doc_type":         "unknown",
    "source_file":      "data/sample_invoices/product_catalogue.pdf",
    "skip_reason":      "Document type not recognised as a logistics document..."
}
```

### Partial extraction (some fields `None`)

```python
{
    "shipper":          "ABC Shipping Co",
    "consignee":        None,
    "origin_port":      "Shenzhen",
    "destination_port": None,          # ← triggers feedback loop
    "container_type":   "LCL",
    "weight_kg":        None,
    "total_cost":       1890.00,
    "currency":         "USD",
    "invoice_date":     None,          # ← triggers feedback loop
    "doc_type":         "freight_quote",
    "source_file":      "data/sample_invoices/quote_002.pdf",
}
```

---

## Step 3 — Feedback Output

`feedback_agent.run(extracted_records, raw_texts)` returns the same list with improvements merged in.

**Input (partial record from above):**
```python
{
    "destination_port": None,
    "invoice_date":     None,
    ...
}
```

**After feedback loop:**
```python
{
    "destination_port": "Hamburg",    # ← recovered by targeted re-extraction
    "invoice_date":     "2025-02-03", # ← recovered by targeted re-extraction
    ...
}
```

**Saved to `core/prompt_memory.json`:**
```json
{
    "freight_quote": [
        "Field 'destination_port' may require alias lookup (was missing in initial pass)",
        "Field 'invoice_date' may require alias lookup (was missing in initial pass)"
    ]
}
```

---

## Step 4 — Dedup Output

`dedup_agent.run(improved_records)` returns a summary dict:

```python
{
    "total_input": 5,
    "saved":       3,
    "skipped":     1,
    "failed":      1,
    "saved_records": [
        {"id": 1, "file": "data/sample_invoices/invoice_001.pdf"},
        {"id": 2, "file": "data/sample_invoices/invoice_002.pdf"},
        {"id": 3, "file": "data/sample_invoices/quote_002.pdf"},
    ],
    "skipped_files": [
        "data/sample_invoices/invoice_001_copy.pdf",   # duplicate
    ],
    "failed_records": [
        {
            "file":   "data/sample_invoices/product_catalogue.pdf",
            "reason": "Document type not recognised as a logistics document."
        }
    ]
}
```

At this point, rows `id=1, 2, 3` are written to the `shipments` table in SQLite.

---

## Step 5 — Calculator Output

`calculator_agent.run()` reads all `shipments` rows and returns analytics:

```python
{
    "total_shipments":   4,
    "valid_for_calc":    3,     # only rows with total_cost != None
    "overall_avg_cost":  2030.00,

    "avg_cost_per_route": {
        "Shanghai → Rotterdam":   2300.00,
        "Shenzhen → Hamburg":     1890.00,
        "Shenzhen → Rotterdam":   1900.00,
    },

    "avg_cost_per_container": {
        "40ft":   2300.00,
        "lcl":    1895.00,
    },

    "most_expensive_route": {
        "route":        "Shanghai → Rotterdam",
        "avg_cost_usd": 2300.00,
    },

    "cheapest_route": {
        "route":        "Shenzhen → Hamburg",
        "avg_cost_usd": 1890.00,
    },

    "monthly_trend": {
        "by_month": {
            "2025-01": 2300.00,
            "2025-02": 1895.00,
        },
        "trend_direction": "⬇ decreasing",
    }
}
```

---

## Step 6 — Freight Output

`freight_agent.run(calc_results)` fetches market rates and computes comparisons:

```python
{
    "fbx_rates": {
        "FBX01": 2100.00,   # China → US West Coast
        "FBX03": 1950.00,   # China → North Europe
        "FBX04": 1800.00,   # China → Mediterranean
    },

    "comparisons": [
        {
            "route":        "Shanghai → Rotterdam",
            "your_avg_usd": 2300.00,
            "market_rate":  1950.00,
            "difference":   350.00,
            "pct_diff":     17.9,
            "overpaying":   False,         # below 20% threshold
            "rate_source":  "FBX Web (FBX03)",
        },
        {
            "route":        "Shenzhen → Hamburg",
            "your_avg_usd": 1890.00,
            "market_rate":  2100.00,       # market is higher
            "difference":   -210.00,
            "pct_diff":     -10.0,
            "overpaying":   False,
            "rate_source":  "FBX Static (FBX03)",
        },
        {
            "route":        "Shenzhen → Rotterdam",
            "your_avg_usd": 1900.00,
            "market_rate":  1950.00,
            "difference":   -50.00,
            "pct_diff":     -2.6,
            "overpaying":   False,
            "rate_source":  "FBX Web (FBX03)",
        },
    ],

    "anomalies": []    # no anomalies — all within 20% threshold
}
```

### Example with anomaly

If `your_avg_usd` were $2,600 on Shanghai → Rotterdam (33% above market):

```python
"anomalies": [
    {
        "type":        "OVERPAYING",
        "severity":    "MEDIUM",
        "route":       "Shanghai → Rotterdam",
        "your_avg":    2600.00,
        "market_rate": 1950.00,
        "pct_diff":    33.3,
        "message":     "Paying 33.3% above market on Shanghai → Rotterdam.",
    }
]
```

---

## Step 7 — Report Output

`report_agent.run(dedup_summary, calc_results, freight_results)` returns a file path:

```python
"outputs/cwt_cpa_report_20250415_143022.txt"
```

The file contains 9 human-readable sections:

```
CROWD WISDOM TRADING — CPA Logistics Cost Report
Generated: 20250415_143022

 MULTI-AGENT PIPELINE ARCHITECTURE
  Pipeline mode: Hermes Orchestrator (sequential tool-calling)
  #   Agent                   Responsibility
  1   IngestionAgent          Loads PDFs: local / GDrive / Gmail
  ...

 DOCUMENT CLASSIFICATION (Agent 2 — ExtractionAgent)
  Successfully extracted : 3
  Skipped (unsupported)  : 1
  Parse failures         : 0

 HERMES FEEDBACK LOOP (Agent 3 — FeedbackAgent)
  Fields recovered via targeted re-extraction : 2
  Fields still missing after re-extraction    : 0

 SECTION 1: Data Ingestion
  Documents processed : 5
  Saved to DB         : 3
  Duplicates skipped  : 1
  Failed/incomplete   : 1

 SECTION 2: Cost Analytics
  Total shipments : 3
  Overall avg cost: $2,030.00
  ...

 SECTION 3: Market Comparison (Shiply / FBX)
  Route                               Your Avg   Market    Diff     %  Source
  ------------------------------------------------------------------------------
  Shanghai → Rotterdam                $2,300.00  $1,950.00  +$350.00  +17.9%   FBX Web

 SECTION 4: Anomalies (0 found)
  No anomalies detected.

 SECTION 5: Summary (AI)
  [LLM executive summary here...]
```

---

## Raw Texts Dict

Between Steps 2 and 3, the orchestrator builds a `raw_texts` dict:

```python
raw_texts = {
    "data/sample_invoices/invoice_001.pdf": "... full PDF text ...",
    "data/sample_invoices/invoice_002.pdf": "... full PDF text ...",
    ...
}
```

This avoids re-parsing PDFs in the feedback agent. The text is captured by calling `extractor_agent._parse_pdf(path)` for each path in `pdf_paths`.
