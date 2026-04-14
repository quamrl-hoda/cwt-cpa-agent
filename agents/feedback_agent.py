"""
feedback_agent.py — Agent 7 (Hermes Feedback Loop)
Analyzes extraction failures and missing fields, then:
  1. Re-runs extraction with an improved prompt
  2. Saves successful prompt hints to prompt_memory.json
  3. Returns improved records for any that were previously incomplete
"""

import json
import logging
from pathlib import Path

from core.llm import ask_llm_json
from core.config import PROMPT_MEMORY
from core.db import log_agent

logger = logging.getLogger(__name__)
AGENT_NAME = "feedback_agent"

# Fields that are critical — if any are missing, trigger feedback loop
CRITICAL_FIELDS = ["shipper", "total_cost", "origin_port", "destination_port", "invoice_date"]


# PUBLIC ENTRY POINT

def run(extracted_records: list[dict], raw_texts: dict[str, str]) -> list[dict]:
    """
    Review extracted records for missing critical fields.
    Re-extract with improved prompts where needed.

    Args:
        extracted_records: List of dicts from extractor_agent.run()
        raw_texts:         Dict mapping source_file path → raw PDF text
                           (pass this from extractor_agent so we don't re-parse)

    Returns:
        Updated list of records (improved versions replace originals).
    """
    logger.info(" [Agent 7] Running feedback loop on %d records...", len(extracted_records))

    improved_records = []
    improvements_made = 0

    for record in extracted_records:
        missing = _find_missing(record)
        source  = record.get("source_file", "unknown")
        doc_type = record.get("doc_type", "unknown")

        #  Skip documents that were already rejected by the extractor 
        if record.get("skip_reason") or doc_type == "unknown":
            logger.info(
                "    [Agent 7] Skipping feedback loop for %s — "
                "document type is unsupported (%s).", source, doc_type
            )
            improved_records.append(record)
            continue

        if not missing:
            improved_records.append(record)
            continue

        logger.info("  Re-extracting %s — missing: %s", source, missing)

        raw_text = raw_texts.get(source, "")
        if not raw_text:
            logger.warning("   No raw text available for %s — cannot re-extract.", source)
            improved_records.append(record)
            continue

        # Build improved prompt using feedback
        improved = _re_extract(raw_text, doc_type, missing, record)

        # If re-extraction filled in new fields → save hints to memory
        newly_filled = [f for f in missing if improved.get(f) is not None]
        if newly_filled:
            _save_prompt_hints(doc_type, missing, newly_filled)
            improvements_made += 1
            logger.info("  Improved fields: %s", newly_filled)
            log_agent(AGENT_NAME, "success", f"Improved fields: {newly_filled}", source)
        else:
            logger.warning("  Still missing after re-extraction: %s", missing)
            log_agent(AGENT_NAME, "failure", f"Still missing: {missing}", source)

        # Merge improved values into the original record
        merged = {**record, **{k: v for k, v in improved.items() if v is not None}}
        merged["source_file"] = source
        merged["doc_type"]    = doc_type
        improved_records.append(merged)

    logger.info(
        " [Agent 7] Feedback loop done. %d/%d records improved.",
        improvements_made, len(extracted_records)
    )
    return improved_records


# HELPERS

def _find_missing(record: dict) -> list[str]:
    """Return list of critical fields that are None or empty."""
    return [
        field for field in CRITICAL_FIELDS
        if record.get(field) is None or record.get(field) == ""
    ]


def _re_extract(raw_text: str, doc_type: str, missing_fields: list[str], prev_record: dict) -> dict:
    """
    Build a targeted re-extraction prompt that focuses on the missing fields.
    Previous partial results are shown to help the model locate context.
    """
    fields_list = "\n".join(f"- {f}" for f in missing_fields)

    prev_str = json.dumps(
        {k: v for k, v in prev_record.items() if k not in ("source_file", "doc_type")},
        indent=2
    )

    prompt = f"""
You are a CPA logistics document extraction specialist.

A previous extraction attempt on a {doc_type} document returned incomplete results.
The following fields are still MISSING and need to be found:

{fields_list}

Previous partial extraction (for context — these fields are already found):
{prev_str}

Please re-read the document carefully and extract ONLY the missing fields listed above.
Look for aliases — for example:
  - "shipper" may appear as "From:", "Seller:", "Exporter:", "Consignor:"
  - "origin_port" may appear as "Port of Loading:", "POL:", "From Port:"
  - "destination_port" may appear as "Port of Discharge:", "POD:", "To Port:"
  - "invoice_date" may appear as "Date:", "Issue Date:", "Invoice No. Date:"
  - "total_cost" may appear as "Total Amount:", "Grand Total:", "Amount Due:", "Freight Charges:"

Respond ONLY with a valid JSON object containing ONLY the missing fields.
If a field truly cannot be found, set it to null.

--- DOCUMENT ---
{raw_text[:3500]}
--- END ---
""".strip()

    return ask_llm_json(prompt)


# PROMPT MEMORY (saves successful hints for extractor_agent to reuse)

def _save_prompt_hints(doc_type: str, originally_missing: list[str], newly_filled: list[str]):
    """
    If re-extraction successfully recovered certain fields, save a hint
    so future extractions start with better prompts.
    """
    try:
        memory_path = Path(PROMPT_MEMORY)
        memory_path.parent.mkdir(parents=True, exist_ok=True)

        memory = {}
        if memory_path.exists():
            with open(memory_path) as f:
                memory = json.load(f)

        if doc_type not in memory:
            memory[doc_type] = []

        # Record which fields needed aliases and were recovered
        for field in newly_filled:
            hint = f"Field '{field}' may require alias lookup (was missing in initial pass)"
            if hint not in memory[doc_type]:
                memory[doc_type].append(hint)

        with open(memory_path, "w") as f:
            json.dump(memory, f, indent=2)

        logger.info("  Saved %d prompt hints to %s", len(newly_filled), PROMPT_MEMORY)

    except Exception as e:
        logger.error("Failed to save prompt memory: %s", e)
