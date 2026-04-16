# Database Schema

CWT CPA Agent uses a single SQLite database at `data/cwt_shipments.db` (configurable via `DB_PATH`). The schema consists of 4 tables, all created by `core/db.py::init_db()`.

---

## Tables Overview

| Table | Purpose |
|---|---|
| `shipments` | Extracted logistics records from PDFs |
| `market_rates` | Fetched freight benchmark rates |
| `anomalies` | Detected overpaying/underpaying anomalies |
| `agent_logs` | Audit trail of all agent operations |

---

## `shipments`

The primary data table. One row per unique shipment document extracted from a PDF.

```sql
CREATE TABLE IF NOT EXISTS shipments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type          TEXT,
    shipper           TEXT,
    consignee         TEXT,
    origin_port       TEXT,
    destination_port  TEXT,
    container_type    TEXT,
    weight_kg         REAL,
    total_cost        REAL,
    currency          TEXT DEFAULT 'USD',
    invoice_date      TEXT,
    source_file       TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Column Details

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER` | Auto-incremented primary key |
| `doc_type` | `TEXT` | `invoice` \| `bill_of_lading` \| `freight_quote` \| `customs_doc` |
| `shipper` | `TEXT` | The sending party (exporter / seller) |
| `consignee` | `TEXT` | The receiving party (importer / buyer) |
| `origin_port` | `TEXT` | Port of loading or origin city |
| `destination_port` | `TEXT` | Port of discharge or destination city |
| `container_type` | `TEXT` | e.g. `20ft`, `40ft`, `LCL`, `FCL` |
| `weight_kg` | `REAL` | Cargo weight in kilograms (converted from lbs if needed) |
| `total_cost` | `REAL` | Total freight cost as a float |
| `currency` | `TEXT` | ISO 4217 code — `USD`, `GBP`, `EUR`, etc. |
| `invoice_date` | `TEXT` | Date string in `YYYY-MM-DD` format |
| `source_file` | `TEXT` | Path to the source PDF file |
| `created_at` | `TIMESTAMP` | Row insertion timestamp (UTC) |

### Deduplication Key

Records are considered duplicates if the following composite key matches an existing row:

```sql
(normalised_shipper, invoice_date, total_cost)
```

Where `normalised_shipper` treats `NULL`, `""`, and whitespace-only values as `""`.

**Dedup check query (from `record_exists()`):**

```sql
SELECT id FROM shipments
WHERE (shipper = ?
   OR (shipper IS NULL AND ? = '')
   OR (shipper = '' AND ? = ''))
  AND invoice_date = ?
  AND total_cost = ?
LIMIT 1
```

---

## `market_rates`

Stores fetched freight benchmark rates from external sources (FBX, Xeneta, Shiply).

```sql
CREATE TABLE IF NOT EXISTS market_rates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_port      TEXT,
    destination_port TEXT,
    market_rate_usd  REAL,
    rate_source      TEXT DEFAULT 'unknown',
    reference_date   TEXT,
    fetched_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Column Details

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER` | Auto-incremented primary key |
| `origin_port` | `TEXT` | Origin corridor or port |
| `destination_port` | `TEXT` | Destination corridor or port |
| `market_rate_usd` | `REAL` | Benchmark rate in USD |
| `rate_source` | `TEXT` | Source: `FBX Web`, `FBX Static (FBX03)`, `Xeneta`, `Shiply`, etc. |
| `reference_date` | `TEXT` | Date the rate applies to (may be empty for static rates) |
| `fetched_at` | `TIMESTAMP` | When the rate was fetched (UTC) |

### Schema Migrations

Two columns were added via migration (applied safely by `init_db()`):
- `rate_source` — added after initial release
- `reference_date` — added after initial release

Both migrations use `ALTER TABLE ... ADD COLUMN` wrapped in `try/except` so they are safe to run on an existing DB.

---

## `anomalies`

Stores detected cost anomalies. Written by `freight_agent` when a route's cost exceeds the anomaly threshold.

```sql
CREATE TABLE IF NOT EXISTS anomalies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT,
    severity     TEXT DEFAULT 'MEDIUM',
    route        TEXT,
    your_avg     REAL,
    market_rate  REAL,
    pct_diff     REAL,
    message      TEXT,
    detected_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Column Details

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER` | Auto-incremented primary key |
| `type` | `TEXT` | `OVERPAYING` \| `UNDERPAYING` |
| `severity` | `TEXT` | `HIGH` (>40%) \| `MEDIUM` (>20%) \| `LOW` |
| `route` | `TEXT` | `"{origin} → {destination}"` |
| `your_avg` | `REAL` | Your average cost on this route (USD) |
| `market_rate` | `REAL` | Benchmark market rate (USD) |
| `pct_diff` | `REAL` | Percentage difference (positive = overpaying) |
| `message` | `TEXT` | Human-readable anomaly description |
| `detected_at` | `TIMESTAMP` | When the anomaly was detected (UTC) |

---

## `agent_logs`

Audit trail of every agent operation — success, failure, and skip events.

```sql
CREATE TABLE IF NOT EXISTS agent_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name  TEXT,
    status      TEXT,
    message     TEXT,
    source_file TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Column Details

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER` | Auto-incremented primary key |
| `agent_name` | `TEXT` | e.g. `loader_agent`, `extractor_agent`, `feedback_agent` |
| `status` | `TEXT` | `success` \| `failure` \| `skipped` |
| `message` | `TEXT` | Short description of what happened |
| `source_file` | `TEXT` | PDF path this event relates to (empty for pipeline-level events) |
| `created_at` | `TIMESTAMP` | Event timestamp (UTC) |

### Agent Names Used

| Agent Name | Written By |
|---|---|
| `loader_agent` | `agents/loader_agent.py` |
| `extractor_agent` | `agents/extractor_agent.py` |
| `feedback_agent` | `agents/feedback_agent.py` |
| `dedup_agent` | `agents/dedup_agent.py` |
| `calculator_agent` | `agents/calculator_agent.py` |

`report_agent` writes its own log at the end with the generated report path.

---

## Useful Queries

### View all shipments

```sql
SELECT id, shipper, origin_port, destination_port, total_cost, currency, invoice_date
FROM shipments
ORDER BY invoice_date;
```

### Average cost per route

```sql
SELECT
    origin_port || ' → ' || destination_port AS route,
    ROUND(AVG(total_cost), 2) AS avg_cost,
    COUNT(*) AS shipment_count
FROM shipments
WHERE total_cost IS NOT NULL
GROUP BY origin_port, destination_port
ORDER BY avg_cost DESC;
```

### All anomalies

```sql
SELECT route, type, severity, your_avg, market_rate, pct_diff, message
FROM anomalies
ORDER BY pct_diff DESC;
```

### Agent success rate

```sql
SELECT
    agent_name,
    status,
    COUNT(*) AS count
FROM agent_logs
GROUP BY agent_name, status
ORDER BY agent_name, status;
```

### Recent failures

```sql
SELECT agent_name, message, source_file, created_at
FROM agent_logs
WHERE status = 'failure'
ORDER BY created_at DESC
LIMIT 20;
```

### Market rates by source

```sql
SELECT
    rate_source,
    COUNT(*) AS count,
    ROUND(AVG(market_rate_usd), 2) AS avg_rate
FROM market_rates
GROUP BY rate_source;
```

---

## Database Location

Default: `data/cwt_shipments.db`

Override via `.env`:

```dotenv
DB_PATH=custom/path/to/my.db
```

The database file and its parent directory are created automatically by `init_db()` on first run.

---

## Resetting the Database

To start fresh, delete the database file:

```bash
# Windows PowerShell
Remove-Item data/cwt_shipments.db

# macOS / Linux
rm data/cwt_shipments.db
```

The next pipeline run will recreate it automatically.
