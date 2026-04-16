import sqlite3
import logging
from pathlib import Path
from core.config import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite DB (creates file if not exists)."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    return conn


def init_db():
    """Create all tables if they don't exist yet. Call once at startup."""
    conn = get_connection()
    cursor = conn.cursor()

    #    Main shipments table   
    cursor.execute("""
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
        )
    """)

    #    Market rates (Shiply + FBX)    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_rates (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_port      TEXT,
            destination_port TEXT,
            market_rate_usd  REAL,
            rate_source      TEXT DEFAULT 'unknown',
            reference_date   TEXT,
            fetched_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: add rate_source column if the DB was created before it existed
    try:
        cursor.execute("ALTER TABLE market_rates ADD COLUMN rate_source TEXT DEFAULT 'unknown'")
        conn.commit()
        logger.info("DB migration: added rate_source column to market_rates")
    except Exception:
        pass  # column already exists — normal case
    # Migration: add reference_date column if missing
    try:
        cursor.execute("ALTER TABLE market_rates ADD COLUMN reference_date TEXT DEFAULT ''")
        conn.commit()
        logger.info("DB migration: added reference_date column to market_rates")
    except Exception:
        pass  # column already exists — normal case

    #    Anomalies  
    cursor.execute("""
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
        )
    """)

    #    Agent run logs     
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name  TEXT,
            status      TEXT,
            message     TEXT,
            source_file TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialised at %s", DB_PATH)


# Shipments helpers

def record_exists(shipper: str, invoice_date: str, total_cost: float) -> bool:
    """
    Return True if a near-duplicate record already exists.

    Dedup key: (normalised_shipper, invoice_date, total_cost)
    Normalisation: None / blank shipper → treat as empty string so that
    the same invoice doesn't slip through when shipper extraction was
    inconsistent across retries.
    Also checks with NULL shipper explicitly to catch rows inserted before
    this normalisation was in place.
    """
    # Normalise: treat None / whitespace-only as empty string
    normalised = (shipper or "").strip()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id FROM shipments
        WHERE (shipper = ? OR (shipper IS NULL AND ? = '') OR (shipper = '' AND ? = ''))
          AND invoice_date = ?
          AND total_cost = ?
        LIMIT 1
        """,
        (normalised, normalised, normalised, invoice_date, total_cost),
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def insert_shipment(data: dict) -> int:
    """Insert a new shipment record. Returns the new row id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO shipments
            (doc_type, shipper, consignee, origin_port, destination_port,
             container_type, weight_kg, total_cost, currency, invoice_date, source_file)
        VALUES
            (:doc_type, :shipper, :consignee, :origin_port, :destination_port,
             :container_type, :weight_kg, :total_cost, :currency, :invoice_date, :source_file)
        """,
        {
            "doc_type":         data.get("doc_type", "unknown"),
            "shipper":          data.get("shipper", ""),
            "consignee":        data.get("consignee", ""),
            "origin_port":      data.get("origin_port", ""),
            "destination_port": data.get("destination_port", ""),
            "container_type":   data.get("container_type", ""),
            "weight_kg":        data.get("weight_kg"),
            "total_cost":       data.get("total_cost"),
            "currency":         data.get("currency", "USD"),
            "invoice_date":     data.get("invoice_date", ""),
            "source_file":      data.get("source_file", ""),
        },
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def fetch_all_shipments() -> list[dict]:
    """Return all shipment rows as a list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shipments ORDER BY invoice_date")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def fetch_shipments_by_route(origin: str, dest: str) -> list[dict]:
    """Return shipment rows for a specific route."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM shipments WHERE origin_port=? AND destination_port=? ORDER BY invoice_date",
        (origin, dest),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# Market rates helpers

def insert_market_rate(
    origin: str,
    destination: str,
    rate_usd: float,
    source: str = "unknown",
    ref_date: str = "",
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO market_rates
           (origin_port, destination_port, market_rate_usd, rate_source, reference_date)
           VALUES (?,?,?,?,?)""",
        (origin, destination, rate_usd, source, ref_date),
    )
    conn.commit()
    conn.close()


def fetch_market_rates() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM market_rates ORDER BY fetched_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# Anomaly helpers

def insert_anomaly(anomaly: dict):
    conn = get_connection()
    conn.execute(
        """INSERT INTO anomalies
           (type, severity, route, your_avg, market_rate, pct_diff, message)
           VALUES (?,?,?,?,?,?,?)""",
        (
            anomaly.get("type"),
            anomaly.get("severity", "MEDIUM"),
            anomaly.get("route"),
            anomaly.get("your_avg"),
            anomaly.get("market_rate"),
            anomaly.get("pct_diff"),
            anomaly.get("message"),
        ),
    )
    conn.commit()
    conn.close()


def fetch_anomalies() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM anomalies ORDER BY detected_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# Agent log helpers

def log_agent(agent_name: str, status: str, message: str, source_file: str = ""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO agent_logs (agent_name, status, message, source_file) VALUES (?,?,?,?)",
        (agent_name, status, message, source_file),
    )
    conn.commit()
    conn.close()


def fetch_agent_logs(agent_name: str | None = None, limit: int = 100) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    if agent_name:
        cursor.execute(
            "SELECT * FROM agent_logs WHERE agent_name=? ORDER BY created_at DESC LIMIT ?",
            (agent_name, limit),
        )
    else:
        cursor.execute(
            "SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows
