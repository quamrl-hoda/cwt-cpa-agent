# CWT CPA Agent — Documentation Hub

> **Crowd Wisdom Trading — Logistics Cost Intelligence System**  
> A 7-agent AI pipeline that ingests freight PDFs, extracts cost data, benchmarks against live market rates, and generates professional CPA reports.

---

## Documentation Index

| Document | Description |
|---|---|
| [Architecture Overview](./architecture.md) | System design, Hermes orchestrator pattern, agent topology |
| [Agents Reference](./agents.md) | All 7 agents — purpose, inputs, outputs, behaviour |
| [Core Modules](./core_modules.md) | `orchestrator`, `db`, `llm`, `config`, `google_auth` |
| [Setup Guide](./setup_guide.md) | Installation, environment variables, running the pipeline |
| [API Reference](./api_reference.md) | Function-level signatures and return types for every module |
| [Data Flow](./data_flow.md) | End-to-end pipeline walkthrough with data shapes at each step |
| [Database Schema](./database_schema.md) | SQLite tables, columns, dedup logic, migrations |
| [Configuration Reference](./configuration.md) | Every `.env` variable explained with defaults and examples |
| [Development Guide](./contributing.md) | Project conventions, extending agents, adding tools |

---

## Quick Summary

```
PDF Files (local / GDrive / Gmail)
         ↓
  HermesOrchestrator (core/orchestrator.py)
         ↓
  Agent 1 · Loader       →  finds & downloads PDFs
  Agent 2 · Extractor    →  classify + extract 9 fields via LLM
  Agent 7 · Feedback     →  Hermes feedback loop, re-extracts missing fields
  Agent 3 · Dedup        →  deduplication + SQLite insert
  Agent 4 · Calculator   →  cost analytics (avg/route/trend)
  Agent 5 · Freight      →  live market rates (FBX + Xeneta + Shiply)
  Agent 6 · Report       →  TXT + HTML CPA report
         ↓
  outputs/cwt_cpa_report_YYYYMMDD_HHMMSS.txt
```

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Orchestration | Hermes-style tool registry (`core/orchestrator.py`) |
| LLM | OpenRouter (any free model — gpt-4o-mini, gemma, mistral) |
| PDF Parsing | Docling (primary) · pypdf (fallback) |
| Market Rates | FBX Web · Xeneta Web · Shiply/Apify · FBX Static |
| Database | SQLite (no ORM, stdlib only) |
| Google Integration | Drive API v3 · Gmail API v1 · OAuth2 |
| Web Scraping | beautifulsoup4 · lxml |

---

*Generated for CWT CPA Agent — Crowd Wisdom Trading internship assessment.*
