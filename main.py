"""
main.py — CWT CPA Agent Orchestrator
=====================================
Runs all 7 agents via the HermesOrchestrator (Hermes-style tool calling).

Usage:
    python main.py                          # local PDFs (Hermes mode)
    python main.py --source gdrive          # loads from Google Drive
    python main.py --source gmail           # loads from Gmail attachments
    python main.py --source gdrive,gmail    # loads from BOTH GDrive + Gmail
    python main.py --source all             # local + gdrive + gmail combined
    python main.py --dry-run                # structural test (no API calls)
    python main.py --list-tools             # print all Hermes tool schemas
    python main.py --legacy                 # bypass orchestrator (sequential mode)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# ── Ensure output dir exists before FileHandler opens the log file ──────────
Path("outputs").mkdir(exist_ok=True)

# ── Force UTF-8 on stdout (Windows cp1252 can't encode route arrows like →/⬆) ─
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("outputs/cwt_agent.log", mode="a", encoding="utf-8"),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)

logger = logging.getLogger("main")

# ── Ensure dirs exist ────────────────────────────────────────────────────────
Path("data/sample_invoices").mkdir(parents=True, exist_ok=True)
Path("core").mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS (used by legacy mode)
# ─────────────────────────────────────────────────────────────────────────────

def _load_all_sources(loader_agent, sources: list[str]) -> list[str]:
    """Run loader_agent for each source; deduplicate by path."""
    seen: set[str] = set()
    combined: list[str] = []
    for src in sources:
        for p in loader_agent.run(source=src.strip()):
            if p not in seen:
                seen.add(p)
                combined.append(p)
    logger.info("Total unique PDFs from all sources: %d", len(combined))
    return combined


def _parse_sources(source_arg: str) -> list[str]:
    if source_arg == "all":
        return ["local", "gdrive", "gmail"]
    valid = {"local", "gdrive", "gmail"}
    parts = [p.strip() for p in source_arg.split(",")]
    bad = [p for p in parts if p not in valid]
    if bad:
        logger.error("Unknown source(s): %s. Valid: local, gdrive, gmail, all", bad)
        sys.exit(1)
    return parts


# ─────────────────────────────────────────────────────────────────────────────
# HERMES MODE  (default — spec-aligned)
# ─────────────────────────────────────────────────────────────────────────────

def _run_via_hermes(source: str, dry_run: bool):
    """Run the full pipeline through the HermesOrchestrator."""
    from core.orchestrator import HermesOrchestrator

    orch = HermesOrchestrator(source=source, dry_run=dry_run)
    logger.info("[Hermes] Registered tools: %s", orch.tool_names())

    result = orch.run_pipeline()

    if "error" in result:
        logger.error(
            "Pipeline aborted at step '%s': %s",
            result.get("step"), result["error"],
        )
        if "No PDFs" in result["error"]:
            print("\nNo PDFs found. Add PDF files to data/sample_invoices/ and run again.")
        return

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline complete!")
    logger.info("   Report  : %s", result.get("report_path", "N/A"))
    logger.info("   DB      : data/cwt_shipments.db")
    logger.info("   Log     : outputs/cwt_agent.log")
    logger.info(
        "   Docs    : %d extracted, %d improved",
        result.get("extracted", 0),
        result.get("improved", 0),
    )
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY MODE  (sequential, no orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

def _run_sequential(source: str):
    """Legacy 7-step sequential pipeline — kept for debugging."""
    from core.db import init_db
    from agents import (
        loader_agent, extractor_agent, dedup_agent,
        calculator_agent, freight_agent, report_agent, feedback_agent,
    )

    init_db()

    logger.info("\n[STEP 1] Loading PDF documents...")
    pdf_paths = _load_all_sources(loader_agent, _parse_sources(source))
    if not pdf_paths:
        logger.error("No PDFs found. Add PDFs to data/sample_invoices/ and retry.")
        print("\nNo PDFs found. Add PDF files to data/sample_invoices/ and run again.")
        return

    logger.info("\n[STEP 2] Classifying and extracting documents...")
    extracted_records = extractor_agent.run(pdf_paths)
    if not extracted_records:
        logger.error("Extraction returned no records. Check your PDFs and OpenRouter key.")
        return

    logger.info("\n[STEP 3] Running Hermes feedback loop...")
    raw_texts = {path: extractor_agent._parse_pdf(path) for path in pdf_paths}
    improved_records = feedback_agent.run(extracted_records, raw_texts)

    logger.info("\n[STEP 4] Deduplicating and saving to database...")
    dedup_summary = dedup_agent.run(improved_records)

    logger.info("\n[STEP 5] Calculating cost analytics...")
    calc_results = calculator_agent.run()

    logger.info("\n[STEP 6] Fetching market freight rates (Shiply + FBX + Xeneta)...")
    freight_results = freight_agent.run(calc_results)

    logger.info("\n[STEP 7] Generating CPA report...")
    report_path = report_agent.run(
        dedup_summary=dedup_summary,
        calc_results=calc_results,
        freight_results=freight_results,
    )

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline complete!")
    logger.info("   Report  : %s", report_path)
    logger.info("   DB      : data/cwt_shipments.db")
    logger.info("   Log     : outputs/cwt_agent.log")
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main(source: str = "local", dry_run: bool = False, use_hermes: bool = True):
    logger.info("=" * 60)
    logger.info(
        "CWT CPA Agent Pipeline starting (source=%s, dry_run=%s, hermes=%s)",
        source, dry_run, use_hermes,
    )
    logger.info("=" * 60)

    if use_hermes:
        _run_via_hermes(source=source, dry_run=dry_run)
    else:
        _run_sequential(source=source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CWT CPA Logistics Agent — powered by Hermes tool orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # local PDFs (Hermes mode, default)
  python main.py --source gdrive          # Google Drive folder
  python main.py --source gmail           # Gmail attachments
  python main.py --source gdrive,gmail    # Both GDrive and Gmail
  python main.py --source all             # All three sources
  python main.py --dry-run                # Test pipeline structure (no API calls)
  python main.py --list-tools             # Print all registered Hermes tool schemas
  python main.py --legacy                 # Use legacy sequential mode
        """,
    )
    parser.add_argument(
        "--source",
        default="local",
        help="Source(s) to load PDFs from. Comma-separated or 'all'. "
             "Choices: local, gdrive, gmail, all  (default: local)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline without LLM or external API calls (structural test).",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use the legacy sequential pipeline instead of the Hermes orchestrator.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print all registered Hermes tool schemas as JSON and exit.",
    )
    args = parser.parse_args()

    if args.list_tools:
        from core.orchestrator import HermesOrchestrator
        orch = HermesOrchestrator(source=args.source)
        print(json.dumps(orch.list_tools(), indent=2))
        sys.exit(0)

    main(
        source=args.source,
        dry_run=args.dry_run,
        use_hermes=not args.legacy,
    )
