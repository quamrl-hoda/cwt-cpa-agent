# Development Guide

How to extend, test, and contribute to CWT CPA Agent.

---

## Project Conventions

### Code Style

- **Python 3.11+** — use modern type syntax (`list[str]`, `dict[str, float]`, `str | None`)
- **Type hints everywhere** — all public functions must have full type annotations
- **Docstrings** — all public functions and classes use Google-style docstrings
- **Logging** — use `logging.getLogger(__name__)` per module; never use `print()` inside agents
- **No direct DB access in agents** — always call `core/db.py` helpers
- **No raw LLM calls in agents** — always call `core/llm.py::ask_llm` or `ask_llm_json`

### File Organisation

```
agents/<name>_agent.py     # one file per agent
core/<module>.py           # shared infrastructure
main.py                    # entry point only; no business logic
```

### Agent Structure

Every agent module must follow this pattern:

```python
import logging
from core.db import log_agent

logger = logging.getLogger(__name__)
AGENT_NAME = "my_agent"   # matches the DB agent_name column

def run(<inputs>) -> <output>:
    """Public entry point — called by orchestrator or directly."""
    logger.info("[Agent N] Description of start")
    
    # ... business logic ...
    
    log_agent(AGENT_NAME, "success", "description of result")
    return result
```

---

## Adding a New Agent

### Step 1 — Create the module

Create `agents/my_new_agent.py`:

```python
import logging
from core.db import log_agent

logger = logging.getLogger(__name__)
AGENT_NAME = "my_new_agent"


def run(some_input: dict) -> dict:
    """
    Describe what this agent does.

    Args:
        some_input: Output from the previous agent.

    Returns:
        Dict with results.
    """
    logger.info("[New Agent] Starting...")

    # Your logic here
    result = {"example": "output"}

    log_agent(AGENT_NAME, "success", "Completed successfully")
    logger.info("[New Agent] Done: %s", result)
    return result
```

### Step 2 — Export from `agents/__init__.py`

```python
# agents/__init__.py
from agents import (
    loader_agent,
    extractor_agent,
    dedup_agent,
    calculator_agent,
    freight_agent,
    report_agent,
    feedback_agent,
    my_new_agent,      # ← add this
)
```

### Step 3 — Register as a Hermes tool in `core/orchestrator.py`

Inside `HermesOrchestrator.__init__()`:

```python
self._register(HermesTool(
    name="my_new_agent",
    description=(
        "Agent N — Short description of what this agent does. "
        "What does it take as input? What does it return?"
    ),
    parameters={
        "type": "object",
        "properties": {
            "some_input": {
                "type": "object",
                "description": "Output dict from calculator_agent.run()",
            }
        },
        "required": ["some_input"],
    },
    fn=lambda some_input: my_new_agent.run(some_input),
))
```

### Step 4 — Wire into `run_pipeline()`

Add a step in the correct position inside `HermesOrchestrator.run_pipeline()`:

```python
# Step N: My new agent
my_result = self.run_tool("my_new_agent", some_input=previous_result)
```

### Step 5 — Add to legacy mode (optional)

In `main.py::_run_sequential()`:

```python
logger.info("\n[STEP N] Running my new agent...")
my_result = my_new_agent.run(previous_result)
```

---

## Adding a New Database Table

### Step 1 — Add `CREATE TABLE` in `core/db.py::init_db()`

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS my_table (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        field_one   TEXT,
        field_two   REAL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
```

### Step 2 — Add helper functions

```python
def insert_my_record(data: dict) -> int:
    """Insert into my_table. Returns new rowid."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO my_table (field_one, field_two) VALUES (?, ?)",
        (data.get("field_one"), data.get("field_two")),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


def fetch_my_records() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM my_table ORDER BY created_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows
```

### Step 3 — Add migration if adding a column to an existing table

```python
# In init_db(), after the CREATE TABLE block:
try:
    cursor.execute("ALTER TABLE my_table ADD COLUMN new_column TEXT DEFAULT ''")
    conn.commit()
except Exception:
    pass  # column already exists
```

---

## Adding a New LLM Prompt

All LLM calls must go through `core/llm.py`. Do not import `requests` directly in agent files.

### For plain text response

```python
from core.llm import ask_llm

result = ask_llm(
    prompt="Your prompt here...",
    system="You are a specialist in X.",
    temperature=0.2,
    max_tokens=500,
)
if result.startswith("ERROR:"):
    logger.error("LLM call failed: %s", result)
    return fallback_value
```

### For JSON response

```python
from core.llm import ask_llm_json

result = ask_llm_json("Extract the following fields as JSON: ...")
if "error" in result:
    logger.error("LLM JSON parse failed: %s", result)
    return {}
```

---

## Adding a New Market Rate Source

The freight agent uses a priority waterfall. To add a new source:

1. Add a new `_try_<source>()` function in `agents/freight_agent.py`
2. Return `(rate_usd: float, source_label: str)` on success, `(None, None)` on failure
3. Insert it into the waterfall in `_get_market_rate_for_route()` before the static fallback

```python
def _get_market_rate_for_route(origin, dest):
    # Level 1: Shiply
    rate, src = _try_shiply(origin, dest)
    if rate: return rate, src

    # Level 2: FBX Web
    rate, src = _try_fbx_web(origin, dest)
    if rate: return rate, src

    # Level 3: Your new source
    rate, src = _try_my_new_source(origin, dest)  # ← insert here
    if rate: return rate, src

    # Level 4: FBX API
    # Level 5: FBX Static
    ...
```

---

## Running Tests

The project does not currently have a dedicated test suite, but the `--dry-run` flag provides structural validation:

```bash
python main.py --dry-run
```

This:
- Initialises the orchestrator and registers all tools
- Calls `init_db()` (creates DB + applies migrations)
- Skips all LLM and external API calls
- Verifies the pipeline can run to completion without crashing

### Manual agent testing

You can test any agent directly in a Python REPL:

```python
from core.db import init_db
init_db()

# Test loader
from agents import loader_agent
paths = loader_agent.run(source="local")
print(paths)

# Test extractor on one file
from agents import extractor_agent
records = extractor_agent.run(paths[:1])
print(records)

# Test calculator (requires DB to have rows)
from agents import calculator_agent
results = calculator_agent.run()
print(results)
```

---

## Prompt Memory

The file `core/prompt_memory.json` is written by `feedback_agent` and read by `extractor_agent`. It should be committed to version control to preserve learned improvements.

**To reset prompt memory** (start fresh with zero hints):

```bash
echo "{}" > core/prompt_memory.json
```

**To inspect current hints:**

```bash
python -c "import json; print(json.dumps(json.load(open('core/prompt_memory.json')), indent=2))"
```

---

## Logging

The pipeline writes two log streams simultaneously:

1. **Console** (`stdout`) — UTF-8, INFO level and above
2. **File** (`outputs/cwt_agent.log`) — UTF-8, INFO level and above, append mode

Log format:
```
HH:MM:SS  LEVEL     module.name - message
```

To increase verbosity (DEBUG level):

```python
# In main.py, change:
logging.basicConfig(level=logging.INFO, ...)
# To:
logging.basicConfig(level=logging.DEBUG, ...)
```

---

## Environment

### Python version

The project requires Python 3.11+ for:
- `list[str]` and `dict[k, v]` type hints in function signatures (PEP 585)
- `str | None` union syntax (PEP 604)
- `Path.write_text(encoding=...)` parameter

### Checking your Python version

```bash
python --version
```

### Using `uv` for version management

```bash
# Install exactly Python 3.11
uv python install 3.11

# Create a venv using that version
uv venv --python 3.11
```

---

## Git Workflow

Files that should be committed to git:

```
✅ agents/*.py
✅ core/*.py  (except prompt_memory.json — see below)
✅ main.py
✅ requirements.txt
✅ .env.example         (not .env!)
✅ core/prompt_memory.json  ← commit to preserve learned hints
✅ docs/
```

Files that should NOT be committed (already in `.gitignore`):

```
❌ .env
❌ credentials.json
❌ token_drive.json
❌ token_gmail.json
❌ data/cwt_shipments.db
❌ data/sample_invoices/
❌ outputs/
❌ .venv/
❌ __pycache__/
```
