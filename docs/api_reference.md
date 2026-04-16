# API Reference

Complete function-level reference for every public API in CWT CPA Agent. Ordered by module.

---

## `main.py`

### `main`

```python
def main(
    source:     str  = "local",
    dry_run:    bool = False,
    use_hermes: bool = True,
) -> None
```

Top-level entry point. Dispatches to `_run_via_hermes()` or `_run_sequential()` based on `use_hermes`.

| Parameter | Type | Description |
|---|---|---|
| `source` | `str` | PDF source: `"local"` \| `"gdrive"` \| `"gmail"` \| `"all"` \| comma-separated |
| `dry_run` | `bool` | Skip all LLM + API calls if `True` |
| `use_hermes` | `bool` | Use `HermesOrchestrator` if `True`, legacy sequential if `False` |

---

### `_parse_sources`

```python
def _parse_sources(source_arg: str) -> list[str]
```

Parses the `--source` CLI argument. `"all"` expands to `["local", "gdrive", "gmail"]`. Validates against `{"local", "gdrive", "gmail"}` and exits on unknown values.

---

### `_load_all_sources`

```python
def _load_all_sources(
    loader_agent,
    sources: list[str],
) -> list[str]
```

Calls `loader_agent.run(source=src)` for each source and merges results. Deduplicates by path using a `set`.

---

## `agents/loader_agent.py`

### `run`

```python
def run(source: str = "local") -> list[str]
```

**Returns:** List of local file paths to PDF files.

| `source` | Behaviour |
|---|---|
| `"local"` | Scans `SAMPLE_PDF_DIR` recursively for `*.pdf` |
| `"gdrive"` | Downloads PDFs from Google Drive folder (OAuth2) |
| `"gmail"` | Downloads PDF attachments from Gmail (OAuth2) |

**Side effects:** Writes `success`/`failure` to `agent_logs` table.

---

## `agents/extractor_agent.py`

### `run`

```python
def run(pdf_paths: list[str]) -> list[dict]
```

**Returns:** List of dicts, one per PDF. Each dict contains:
- 9 extracted field keys (see [Agents Reference](./agents.md#extracted-fields))
- `doc_type: str`
- `source_file: str`
- `skip_reason: str` (only if classified as `"unknown"`)

---

### `_parse_pdf` *(internal, but used by orchestrator)*

```python
def _parse_pdf(path: str) -> str
```

Parses a PDF to plain text (Docling → pypdf fallback). Returns empty string on failure.

> **Note:** The orchestrator accesses this directly as `self._extractor._parse_pdf(path)` to build the `raw_texts` dict for the feedback agent.

---

## `agents/dedup_agent.py`

### `run`

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
    "saved_records":  list[dict],   # [{"id": int, "file": str}]
    "skipped_files":  list[str],
    "failed_records": list[dict],   # [{"file": str, "reason": str}]
}
```

---

## `agents/calculator_agent.py`

### `run`

```python
def run() -> dict
```

Reads all `shipments` rows from DB. **Returns:**

```python
{
    "total_shipments":        int,
    "valid_for_calc":         int,
    "overall_avg_cost":       float,
    "avg_cost_per_route":     dict[str, float],
    "avg_cost_per_container": dict[str, float],
    "most_expensive_route":   dict,    # {"route": str, "avg_cost_usd": float}
    "cheapest_route":         dict,    # {"route": str, "avg_cost_usd": float}
    "monthly_trend":          dict,    # {"by_month": {...}, "trend_direction": str}
}
```

Or `{"error": "No shipments found in DB"}` if DB is empty.

---

## `agents/freight_agent.py`

### `run`

```python
def run(calc_results: dict) -> dict
```

**Returns:**

```python
{
    "fbx_rates":   dict[str, float],   # {"FBX01": 2100.0, ...}
    "comparisons": list[dict],
    "anomalies":   list[dict],
}
```

**Comparison dict shape:**

```python
{
    "route":        str,
    "your_avg_usd": float,
    "market_rate":  float | None,
    "difference":   float | None,
    "pct_diff":     float | None,
    "overpaying":   bool,
    "rate_source":  str,
}
```

**Anomaly dict shape:**

```python
{
    "type":        "OVERPAYING" | "UNDERPAYING",
    "severity":    "HIGH" | "MEDIUM" | "LOW",
    "route":       str,
    "your_avg":    float,
    "market_rate": float,
    "pct_diff":    float,
    "message":     str,
}
```

---

## `agents/report_agent.py`

### `run`

```python
def run(
    dedup_summary:   dict,
    calc_results:    dict,
    freight_results: dict,
) -> str
```

**Returns:** Path string to the generated `.txt` report file (e.g. `"outputs/cwt_cpa_report_20250415_143022.txt"`).

**Side effects:**
- Creates `outputs/` directory if needed
- Writes `.txt` report file
- Prints brief summary to stdout
- Writes `success` entry to `agent_logs`

---

## `agents/feedback_agent.py`

### `run`

```python
def run(
    extracted_records: list[dict],
    raw_texts:         dict[str, str],
) -> list[dict]
```

**Returns:** Updated list of records. Improved values are merged into original records. Shape is identical to `extractor_agent.run()` output.

---

## `core/config.py`

All values are module-level constants. Import directly:

```python
from core.config import OPENROUTER_API_KEY, LLM_MODEL, DB_PATH, ANOMALY_THRESHOLD_PCT
```

See [Configuration Reference](./configuration.md) for the full table.

---

## `core/llm.py`

### `ask_llm`

```python
def ask_llm(
    prompt:      str,
    system:      str   = "You are a helpful logistics and CPA assistant.",
    temperature: float = 0.2,
    max_tokens:  int   = 1500,
) -> str
```

**Returns:** Model reply as a plain string, or `"ERROR: ..."` on failure.

**Raises:** `EnvironmentError` if `OPENROUTER_API_KEY` is not set.

---

### `ask_llm_json`

```python
def ask_llm_json(
    prompt: str,
    system: str = "You are a helpful logistics and CPA assistant.",
) -> dict
```

**Returns:** Parsed JSON `dict`, or `{"error": str, "raw": str}` on failure.

Uses `temperature=0.1` internally (lower for deterministic JSON output).

---

## `core/db.py`

### Connection

```python
def get_connection() -> sqlite3.Connection
```

Returns open connection with `row_factory = sqlite3.Row`. **Caller must close it.**

---

### Initialisation

```python
def init_db() -> None
```

Creates all 4 tables and applies schema migrations. Safe to call multiple times (idempotent).

---

### Shipments

```python
def insert_shipment(data: dict) -> int
```
Returns new `rowid`.

```python
def fetch_all_shipments() -> list[dict]
```
All rows ordered by `invoice_date ASC`.

```python
def fetch_shipments_by_route(origin: str, dest: str) -> list[dict]
```
Rows filtered by exact match on `origin_port` and `destination_port`.

```python
def record_exists(
    shipper:      str,
    invoice_date: str,
    total_cost:   float,
) -> bool
```
Dedup check with shipper normalisation.

---

### Market Rates

```python
def insert_market_rate(
    origin:      str,
    destination: str,
    rate_usd:    float,
    source:      str = "unknown",
    ref_date:    str = "",
) -> None
```

```python
def fetch_market_rates() -> list[dict]
```
All rows ordered by `fetched_at DESC`.

---

### Anomalies

```python
def insert_anomaly(anomaly: dict) -> None
```
Keys used: `type`, `severity`, `route`, `your_avg`, `market_rate`, `pct_diff`, `message`.

```python
def fetch_anomalies() -> list[dict]
```
All rows ordered by `detected_at DESC`.

---

### Agent Logs

```python
def log_agent(
    agent_name:  str,
    status:      str,
    message:     str,
    source_file: str = "",
) -> None
```
`status` should be `"success"`, `"failure"`, or `"skipped"`.

```python
def fetch_agent_logs(
    agent_name: str | None = None,
    limit:      int         = 100,
) -> list[dict]
```
Returns up to `limit` rows, newest first. Pass `agent_name=None` to fetch all agents.

---

## `core/orchestrator.py`

### `HermesTool`

```python
@dataclass
class HermesTool:
    name:        str
    description: str
    parameters:  dict       # JSON Schema
    fn:          Callable
    result:      Any = None
```

**`__call__(**kwargs) -> Any`** — Calls `self.fn(**kwargs)`, stores result, returns it.

**`to_schema() -> dict`** — Returns OpenAI / Hermes function-calling compatible schema dict.

---

### `HermesOrchestrator`

```python
class HermesOrchestrator:
    def __init__(self, source: str = "local", dry_run: bool = False)
```

**`run_pipeline() -> dict`**

Runs all 7 tools in order. Returns:
```python
{
    "pdf_paths":       list[str],
    "extracted":       int,
    "improved":        int,
    "dedup_summary":   dict,
    "calc_results":    dict,
    "freight_results": dict,
    "report_path":     str,
}
```
On error: `{"error": str, "step": str}`.

**`run_tool(name: str, **kwargs) -> Any`**

Runs a single registered tool. Raises `ValueError` for unknown names.

**`list_tools() -> list[dict]`**

Returns all tool schemas (Hermes/OpenAI format).

**`tool_names() -> list[str]`**

Returns `["loader", "extractor", "feedback", "dedup", "calculator", "freight", "report"]`.

---

## `core/google_auth.py`

### `get_drive_service`

```python
def get_drive_service(credentials_file: str)
```

Returns an authenticated Google Drive v3 service object. Caches token in `token_drive.json`.

**Raises:** `RuntimeError` if `credentials_file` is not found.

---

### `get_gmail_service`

```python
def get_gmail_service(credentials_file: str)
```

Returns an authenticated Gmail v1 service object. Caches token in `token_gmail.json`.

**Raises:** `RuntimeError` if `credentials_file` is not found.
