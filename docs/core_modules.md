# Core Modules Reference

The `core/` package provides shared infrastructure used by all agents. No agent should directly access the database, call the LLM, or read environment variables — they must go through these modules.

---

## `core/config.py` — Configuration

Loads `.env` via `python-dotenv` and exposes all configuration as module-level constants.

### Constants

#### LLM / OpenRouter

| Constant | Source | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | `OPENROUTER_API_KEY` env | `""` | API key for OpenRouter |
| `OPENROUTER_BASE_URL` | hardcoded | `https://openrouter.ai/api/v1/chat/completions` | Endpoint |
| `LLM_MODEL` | `LLM_MODEL` env | `"openai/gpt-4o-mini"` | Model identifier |

#### Apify / Market Rates

| Constant | Source | Default | Description |
|---|---|---|---|
| `APIFY_TOKEN` | `APIFY_TOKEN` env | `""` | Apify API token |
| `SHIPLY_ACTOR_ID` | `SHIPLY_ACTOR_ID` env | `"parseforge/shiply-com-freight-marketplace-scraper"` | Shiply actor |
| `APIFY_FREIGHT_ACTOR` | `APIFY_FREIGHT_ACTOR` env | `"vinaybhosle/shippingrates-mcp"` | Legacy actor |

#### Google Integration

| Constant | Source | Default | Description |
|---|---|---|---|
| `GOOGLE_CREDENTIALS_FILE` | `GOOGLE_CREDENTIALS_FILE` env | `"credentials.json"` | OAuth2 credentials path |
| `GDRIVE_FOLDER_ID` | `GDRIVE_FOLDER_ID` env | `""` | Target Drive folder |
| `GDRIVE_RECURSIVE` | `GDRIVE_RECURSIVE` env | `True` | Scan sub-folders |
| `GMAIL_SEARCH_QUERY` | `GMAIL_SEARCH_QUERY` env | *(shipping/invoice/freight with attachment)* | Gmail search |
| `GMAIL_MAX_RESULTS` | `GMAIL_MAX_RESULTS` env | `30` | Max emails to scan |

#### Paths and Thresholds

| Constant | Value | Description |
|---|---|---|
| `DB_PATH` | `"data/cwt_shipments.db"` | SQLite database file |
| `SAMPLE_PDF_DIR` | `"data/sample_invoices"` | Local PDF folder |
| `OUTPUT_DIR` | `"outputs"` | Report output folder |
| `PROMPT_MEMORY` | `"core/prompt_memory.json"` | Feedback hints file |
| `ANOMALY_THRESHOLD_PCT` | `20` | % above market rate to flag anomaly |
| `REPORT_FORMAT` | `"txt"` | Output format: `"txt"` \| `"html"` \| `"txt,html"` |

---

## `core/llm.py` — LLM Wrapper

Provides two functions that wrap the OpenRouter chat completions API with retry logic, JSON parsing, and error handling.

### `ask_llm`

```python
def ask_llm(
    prompt: str,
    system: str = "You are a helpful logistics and CPA assistant.",
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> str
```

Sends a prompt to OpenRouter and returns the model's reply as a plain string.

**Retry behaviour:**
- Retries up to `_MAX_RETRIES = 3` times on transient network errors
- Uses exponential backoff: 2s → 4s → 8s
- Retried exceptions: `ConnectionError`, `Timeout`, `ChunkedEncodingError`
- HTTP errors (4xx/5xx) are **not** retried — returned immediately as `"ERROR: HTTP ..."`
- Null content from the model returns `"ERROR: LLM returned no content ..."`

**On failure:** Returns a string starting with `"ERROR:"` — callers should check for this prefix.

### `ask_llm_json`

```python
def ask_llm_json(
    prompt: str,
    system: str = "You are a helpful logistics and CPA assistant.",
) -> dict
```

Like `ask_llm()` but forces JSON output. Automatically:
1. Appends `"Respond ONLY with valid JSON..."` to the system prompt
2. Strips markdown code fences (` ```json ... ``` `) that some models include
3. Parses and returns the JSON as a `dict`

**On failure:** Returns `{"error": "JSON parse failed: ...", "raw": "..."}`.

### Configuration

```python
_MAX_RETRIES   = 3
_RETRY_BACKOFF = 2.0   # seconds (doubles each attempt)
```

---

## `core/db.py` — Database Helpers

All SQLite access goes through this module. Uses `sqlite3` from the standard library with `row_factory = sqlite3.Row` so rows behave like dicts.

### Connection

```python
def get_connection() -> sqlite3.Connection
```

Creates the DB file and parent directories if they don't exist. Returns an open connection — callers are responsible for closing it.

### Initialisation

```python
def init_db()
```

Creates all 4 tables if they don't already exist, then applies migrations (adds `rate_source` and `reference_date` columns to `market_rates` if missing). Called once at pipeline startup.

### Shipment Functions

```python
def insert_shipment(data: dict) -> int
```
Inserts a new row into `shipments`. Returns the new `rowid`.

```python
def fetch_all_shipments() -> list[dict]
```
Returns all rows from `shipments` ordered by `invoice_date`.

```python
def fetch_shipments_by_route(origin: str, dest: str) -> list[dict]
```
Returns rows for a specific `origin_port → destination_port` pair.

```python
def record_exists(shipper: str, invoice_date: str, total_cost: float) -> bool
```
Deduplication check. Normalises `shipper` (treats `None`/blank as `""`).

### Market Rate Functions

```python
def insert_market_rate(
    origin: str,
    destination: str,
    rate_usd: float,
    source: str = "unknown",
    ref_date: str = "",
)
```

```python
def fetch_market_rates() -> list[dict]
```
Returns all rows from `market_rates` ordered by `fetched_at DESC`.

### Anomaly Functions

```python
def insert_anomaly(anomaly: dict)
```
Inserts an anomaly record. `anomaly` dict keys: `type`, `severity`, `route`, `your_avg`, `market_rate`, `pct_diff`, `message`.

```python
def fetch_anomalies() -> list[dict]
```

### Agent Log Functions

```python
def log_agent(agent_name: str, status: str, message: str, source_file: str = "")
```
Records an agent run event. `status` should be one of: `"success"`, `"failure"`, `"skipped"`.

```python
def fetch_agent_logs(agent_name: str | None = None, limit: int = 100) -> list[dict]
```
Returns logs filtered by agent name (or all agents if `None`), newest first.

---

## `core/orchestrator.py` — Hermes Orchestrator

### `HermesTool`

```python
@dataclass
class HermesTool:
    name:        str
    description: str
    parameters:  dict     # JSON Schema
    fn:          Callable
    result:      Any = None
```

**`__call__(**kwargs)`** — Executes `self.fn(**kwargs)`, stores result in `self.result`, returns result.

**`to_schema() -> dict`** — Returns OpenAI / Hermes function-calling compatible schema.

### `HermesOrchestrator`

```python
class HermesOrchestrator:
    def __init__(self, source: str = "local", dry_run: bool = False)
```

Constructor registers all 7 agents as tools and calls `init_db()`.

**`run_pipeline() -> dict`**

Executes all tools in order. Returns a summary dict:

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

Run a single registered tool by name. Raises `ValueError` for unknown tool names.

**`list_tools() -> list[dict]`**

Returns all registered tool schemas (useful for `--list-tools` CLI option).

**`tool_names() -> list[str]`**

Returns names of all registered tools: `["loader", "extractor", "feedback", "dedup", "calculator", "freight", "report"]`.

---

## `core/google_auth.py` — Google OAuth2

Provides authenticated service objects for the Drive and Gmail APIs.

### `get_drive_service(credentials_file: str)`

Builds and returns a Google Drive v3 API service client. Handles the full OAuth2 flow:
- Loads token from `token_drive.json` if it exists
- Refreshes expired tokens automatically
- Opens a browser for consent on first run
- Saves the new token to `token_drive.json`

Required OAuth2 scopes:
- `https://www.googleapis.com/auth/drive.readonly`

### `get_gmail_service(credentials_file: str)`

Same pattern as `get_drive_service` but for Gmail v1 API.  
Token cached in `token_gmail.json`.

Required OAuth2 scopes:
- `https://www.googleapis.com/auth/gmail.readonly`

### `credentials.json`

Download from **Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON**. Required for both Drive and Gmail integration.

---

## `core/prompt_memory.json`

A JSON file written and read by the feedback/extractor agents to implement persistent prompt improvement.

**Written by:** `feedback_agent._save_prompt_hints()`  
**Read by:** `extractor_agent._load_prompt_hints()`

**Format:**

```json
{
  "invoice": [
    "Field 'destination_port' may require alias lookup (was missing in initial pass)"
  ],
  "bill_of_lading": [],
  "freight_quote": [
    "Field 'shipper' may require alias lookup (was missing in initial pass)"
  ]
}
```

Keys are document type strings from `DOC_TYPES`. Values are lists of hint strings appended to the next extraction prompt.

Commit this file to version control to preserve learned extraction improvements across environments.
