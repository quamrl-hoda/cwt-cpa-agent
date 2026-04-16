# Architecture Overview

## Design Philosophy

CWT CPA Agent is built as a **multi-agent pipeline** modelled on the **Hermes tool-calling pattern**. Each of the 7 agents is registered as a named tool in a central orchestrator. The orchestrator calls them in a fixed order, threading outputs from one agent as inputs to the next.

This gives you:
- **Auditability** — every tool call is logged with name, input, and output
- **Modularity** — agents can be unit-tested individually
- **Extensibility** — new agents are added by registering a new `HermesTool`
- **Dry-run support** — the pipeline skeleton runs without any real API calls

---

## High-Level Topology

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │               HermesOrchestrator                    │   │
│   │              core/orchestrator.py                   │   │
│   │                                                     │   │
│   │   Tool Registry                                     │   │
│   │   ┌──────────┐  ┌──────────┐  ┌──────────┐         │   │
│   │   │  loader  │  │extractor │  │ feedback │  ...    │   │
│   │   └──────────┘  └──────────┘  └──────────┘         │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼  Pipeline execution (sequential)
┌────────────────────────────────────────────────────────────┐
│  Step 1 · loader_agent       agents/loader_agent.py        │
│  Step 2 · extractor_agent    agents/extractor_agent.py     │
│  Step 3 · feedback_agent     agents/feedback_agent.py      │  ← Hermes loop
│  Step 4 · dedup_agent        agents/dedup_agent.py         │
│  Step 5 · calculator_agent   agents/calculator_agent.py    │
│  Step 6 · freight_agent      agents/freight_agent.py       │
│  Step 7 · report_agent       agents/report_agent.py        │
└────────────────────────────────────────────────────────────┘
         │
         ▼  Shared infrastructure
┌────────────────────────────────────────────────────────────┐
│  core/config.py        Environment variables + paths       │
│  core/db.py            SQLite helpers (4 tables)           │
│  core/llm.py           OpenRouter wrapper + retry logic    │
│  core/google_auth.py   OAuth2 for Drive + Gmail            │
│  core/prompt_memory.json  Learned extraction hints         │
└────────────────────────────────────────────────────────────┘
```

---

## Execution Modes

### Hermes Mode (default)

```bash
python main.py
```

- Instantiates `HermesOrchestrator`
- Registers all 7 agents as `HermesTool` objects
- Calls `run_pipeline()` which executes them in order
- Each step's output is passed to the next step as kwargs

### Legacy Sequential Mode

```bash
python main.py --legacy
```

- Bypasses the orchestrator
- Imports agents directly and calls `.run()` in a plain Python sequence
- Useful for debugging individual agents without the tool-call overhead

### Dry Run Mode

```bash
python main.py --dry-run
```

- Runs the pipeline structure (initialises orchestrator, registers tools)
- Skips all real LLM and external API calls
- Used for CI/integration testing

---

## Hermes Tool Pattern

Each agent is wrapped in a `HermesTool` dataclass:

```python
@dataclass
class HermesTool:
    name:        str          # unique identifier, e.g. "loader"
    description: str          # human-readable explanation
    parameters:  dict         # JSON Schema describing inputs
    fn:          Callable     # agent's run() function (or lambda wrapper)
    result:      Any = None   # populated after execution
```

The `to_schema()` method returns an **OpenAI / Hermes function-calling compatible schema**:

```json
{
  "type": "function",
  "function": {
    "name": "loader",
    "description": "Agent 1 — Loads PDF documents ...",
    "parameters": {
      "type": "object",
      "properties": {
        "source": { "type": "string", "enum": ["local", "gdrive", "gmail", "all"] }
      },
      "required": ["source"]
    }
  }
}
```

You can inspect all registered schemas at runtime:

```bash
python main.py --list-tools
```

---

## Data Flow Between Agents

```
loader.run(source)
   → list[str]                           (local file paths to PDFs)

extractor.run(pdf_paths)
   → list[dict]                          (one dict per PDF, 9 extracted fields)

feedback.run(extracted_records, raw_texts)
   → list[dict]                          (same shape, missing fields filled in)

dedup.run(extracted_records)
   → dict                                (summary: saved / skipped / failed counts)

calculator.run()
   → dict                                (avg costs, routes, trend, extremes)

freight.run(calc_results)
   → dict                                (market rates, comparisons, anomalies)

report.run(dedup_summary, calc_results, freight_results)
   → str                                 (path to generated TXT report file)
```

---

## Feedback Loop (Hermes Pattern)

The feedback agent (`Agent 7`) implements the **Hermes prompt-improvement loop**:

1. Reviews each extracted record for missing **critical fields**:  
   `shipper`, `total_cost`, `origin_port`, `destination_port`, `invoice_date`
2. Builds a **targeted re-extraction prompt** that shows the model what was already found and focuses only on missing fields
3. Merges improved values back into the record
4. **Saves successful hints** to `core/prompt_memory.json`
5. On the next pipeline run, `extractor_agent` loads these hints and adds them to the initial extraction prompt — the system gets smarter over time

---

## Source Routing

```
--source local       → agents/loader_agent.py::_load_local()
--source gdrive      → agents/loader_agent.py::_load_gdrive()
--source gmail       → agents/loader_agent.py::_load_gmail()
--source gdrive,gmail → _load_gdrive() + _load_gmail() combined, deduplicated by path
--source all         → local + gdrive + gmail combined, deduplicated by path
```

---

## Market Rate Waterfall (Agent 5)

Agent 5 tries 5 sources in order, stopping at the first success per route:

```
Level 1  Shiply via Apify        → real marketplace quotes  (paid plan required)
Level 2  FBX Web Scraper         → live fbx.freightos.com   (free, best-effort)
Level 3  Xeneta Web Scraper      → live xeneta.com indices   (free, best-effort)
Level 4  FBX REST API            → Freightos public API      (often 403)
Level 5  FBX Static Fallback     → hardcoded Q1-2025 rates   (always available)
```

If a route's ports match a known FBX corridor (e.g. China → N. Europe = FBX03), the static fallback provides meaningful benchmark data even with zero API keys configured.

---

## Directory Layout

```
cwt-cpa-agent/
├── agents/                     # 7 agent modules
│   ├── __init__.py
│   ├── loader_agent.py         # Agent 1
│   ├── extractor_agent.py      # Agent 2
│   ├── dedup_agent.py          # Agent 3
│   ├── calculator_agent.py     # Agent 4
│   ├── freight_agent.py        # Agent 5
│   ├── report_agent.py         # Agent 6
│   └── feedback_agent.py       # Agent 7 (Hermes loop)
├── core/                       # Shared infrastructure
│   ├── config.py               # .env loading + constants
│   ├── db.py                   # SQLite helpers
│   ├── llm.py                  # OpenRouter wrapper
│   ├── orchestrator.py         # HermesOrchestrator + HermesTool
│   ├── google_auth.py          # OAuth2 service builders
│   └── prompt_memory.json      # Learned extraction hints
├── data/
│   ├── cwt_shipments.db        # SQLite database (auto-created)
│   └── sample_invoices/        # Drop PDFs here
├── outputs/                    # Generated reports + log
│   ├── cwt_cpa_report_*.txt
│   └── cwt_agent.log
├── docs/                       # This documentation
├── main.py                     # Entry point
├── requirements.txt
├── .env.example
└── README.md
```
