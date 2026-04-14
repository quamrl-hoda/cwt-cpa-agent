"""
main.py — CWT CPA Agent Orchestrator
=====================================
Runs all 7 agents in sequence.

Usage:
    python main.py                          # loads PDFs from local folder
    python main.py --source gdrive          # loads from Google Drive
    python main.py --source gmail           # loads from Gmail attachments
    python main.py --source gdrive,gmail    # loads from BOTH GDrive + Gmail
    python main.py --source all             # local + gdrive + gmail combined
"""

import argparse
import logging
import sys
from pathlib import Path

# ── Ensure output dir exists before FileHandler opens the log file ──────────
Path("outputs").mkdir(exist_ok=True)

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

# ── Agent imports ─────────────────────────────────────────────────────────────
from core.db import init_db
from agents import (
    loader_agent,
    extractor_agent,
    dedup_agent,
    calculator_agent,
    freight_agent,
    report_agent,
    feedback_agent,
)


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-SOURCE LOADER
# ─────────────────────────────────────────────────────────────────────────────

def _load_all_sources(sources: list[str]) -> list[str]:
    """
    Run loader_agent for each requested source and combine the results.
    Deduplicates by file path so the same file isn't processed twice.
    """
    seen: set[str] = set()
    combined: list[str] = []

    for src in sources:
        src = src.strip()
        logger.info("Loading from source: %s", src)
        paths = loader_agent.run(source=src)
        for p in paths:
            if p not in seen:
                seen.add(p)
                combined.append(p)

    logger.info("Total unique PDFs from all sources: %d", len(combined))
    return combined


def _parse_sources(source_arg: str) -> list[str]:
    """
    Convert the --source argument into a list of source names.

    Accepts:
      "local"            → ["local"]
      "gdrive"           → ["gdrive"]
      "gmail"            → ["gmail"]
      "gdrive,gmail"     → ["gdrive", "gmail"]
      "all"              → ["local", "gdrive", "gmail"]
    """
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
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def main(source: str = "local"):
    logger.info("=" * 60)
    logger.info("CWT CPA Agent Pipeline starting (source=%s)", source)
    logger.info("=" * 60)

    # ── 0. Initialise DB ──────────────────────────────────────────────────
    init_db()

    # ── 1. Load PDFs (one or more sources) ────────────────────────────────
    logger.info("\n[STEP 1] Loading PDF documents...")
    sources = _parse_sources(source)
    pdf_paths = _load_all_sources(sources)

    if not pdf_paths:
        logger.error("No PDFs found. Add PDFs to data/sample_invoices/ and retry.")
        print("\nNo PDFs found. Add PDF files to data/sample_invoices/ and run again.")
        return

    # ── 2. Classify + Extract ─────────────────────────────────────────────
    logger.info("\n[STEP 2] Classifying and extracting documents...")
    extracted_records = extractor_agent.run(pdf_paths)

    if not extracted_records:
        logger.error("Extraction returned no records. Check your PDFs and OpenRouter key.")
        return

    # ── 3. Hermes Feedback Loop ───────────────────────────────────────────
    logger.info("\n[STEP 3] Running Hermes feedback loop...")
    raw_texts = {
        path: extractor_agent._parse_pdf(path)
        for path in pdf_paths
    }
    improved_records = feedback_agent.run(extracted_records, raw_texts)

    # ── 4. Deduplicate + Save ─────────────────────────────────────────────
    logger.info("\n[STEP 4] Deduplicating and saving to database...")
    dedup_summary = dedup_agent.run(improved_records)

    # ── 5. Calculate Cost Analytics ───────────────────────────────────────
    logger.info("\n[STEP 5] Calculating cost analytics...")
    calc_results = calculator_agent.run()

    # ── 6. Fetch Market Rates (Shiply / FBX) ─────────────────────────────
    logger.info("\n[STEP 6] Fetching market freight rates (Shiply + FBX)...")
    freight_results = freight_agent.run(calc_results)

    # ── 7. Generate Reports ───────────────────────────────────────────────
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CWT CPA Logistics Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # local PDFs only
  python main.py --source gdrive          # Google Drive folder
  python main.py --source gmail           # Gmail attachments
  python main.py --source gdrive,gmail    # Both GDrive and Gmail
  python main.py --source all             # All three sources
        """,
    )
    parser.add_argument(
        "--source",
        default="local",
        help="Source(s) to load PDFs from. Comma-separated or 'all'. "
             "Choices: local, gdrive, gmail, all  (default: local)",
    )
    args = parser.parse_args()
    main(source=args.source)
