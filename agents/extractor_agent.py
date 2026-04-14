"""
extractor_agent.py — Agent 2
Two sub-agents:
  A) Classifier  — asks LLM what type of document this is
  B) Extractor   — uses Docling to parse PDF then asks LLM to extract fields

Returns a list of dicts (one per PDF).
"""

import logging
import json
from pathlib import Path

from core.llm import ask_llm_json, ask_llm
from core.db import log_agent
from core.config import PROMPT_MEMORY

logger = logging.getLogger(__name__)
AGENT_NAME = "extractor_agent"

# Fields we want to extract from every document
EXTRACT_FIELDS = [
    "shipper",
    "consignee",
    "origin_port",
    "destination_port",
    "container_type",   # e.g. 20ft, 40ft, LCL
    "weight_kg",
    "total_cost",
    "currency",
    "invoice_date",     # YYYY-MM-DD preferred
]

DOC_TYPES = ["invoice", "bill_of_lading", "freight_quote", "customs_doc", "unknown"]


# PUBLIC ENTRY POINT

def run(pdf_paths: list[str]) -> list[dict]:
    """
    Process a list of PDF file paths.

    Returns:
        List of dicts with extracted fields + doc_type + source_file.
    """
    results = []

    for path in pdf_paths:
        logger.info("[Agent 2] Processing: %s", path)

        # Step 1 — parse PDF to text
        raw_text = _parse_pdf(path)
        if not raw_text:
            log_agent(AGENT_NAME, "failure", "Could not parse PDF", path)
            logger.warning(" [Agent 2] Empty text from %s — skipping.", path)
            continue

        # Step 2 — classify
        doc_type = _classify(raw_text)
        logger.info("  Classified as: %s", doc_type)

        # Step 3 — skip non-logistics documents entirely
        if doc_type == "unknown":
            logger.warning(
                "  [Agent 2] Skipping %s — classified as 'unknown' "
                "(not a supported logistics document type). "
                "Supported types: %s", path, DOC_TYPES[:-1]
            )
            log_agent(AGENT_NAME, "skipped", "unsupported document type", path)
            # Return a shell record so downstream agents know this file was seen
            results.append({
                field: None for field in EXTRACT_FIELDS
            } | {
                "doc_type":    "unknown",
                "source_file": path,
                "skip_reason": "Document type not recognised as a logistics document. "
                               "Ensure the file is an invoice, bill of lading, freight quote, or customs doc.",
            })
            continue

        # Step 4 — extract fields
        extracted = _extract(raw_text, doc_type, path)
        extracted["doc_type"]    = doc_type
        extracted["source_file"] = path

        results.append(extracted)
        log_agent(AGENT_NAME, "success", f"Extracted {len(extracted)} fields", path)
        logger.info(" [Agent 2] Extracted: %s", extracted)

    return results


# STEP 1 — PDF PARSING (Docling)

def _parse_pdf(path: str) -> str:
    """
    Use Docling to convert PDF to plain text.
    Falls back to pypdf if Docling is unavailable.
    """
    #   Try Docling first  
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(path)
        text = result.document.export_to_markdown()
        logger.debug("Docling parsed %d chars from %s", len(text), path)
        return text

    except ImportError:
        logger.warning("Docling not installed. Falling back to pypdf.")

    #    Fallback: pypdf    
    try:
        import pypdf

        reader = pypdf.PdfReader(path)
        pages  = [page.extract_text() or "" for page in reader.pages]
        text   = "\n".join(pages)
        logger.debug("pypdf parsed %d chars from %s", len(text), path)
        return text

    except ImportError:
        logger.error("Neither Docling nor pypdf is installed. Run: pip install docling  OR  pip install pypdf")
        return ""

    except Exception as e:
        logger.error("PDF parse error for %s: %s", path, e)
        return ""


# STEP 2 — CLASSIFIER SUB-AGENT

def _classify(text: str) -> str:
    """Ask the LLM to classify the document type."""
    # Only send first 1500 chars — enough for classification, saves tokens
    snippet = text[:1500]

    prompt = f"""
You are a logistics document classifier.

Given the following document text, classify it as one of:
{DOC_TYPES}

Respond with ONLY the label (e.g. "invoice"). No explanation.

--- DOCUMENT START ---
{snippet}
--- DOCUMENT END ---
""".strip()

    result = ask_llm(prompt, temperature=0.0, max_tokens=20)
    # Clean up and validate
    label = result.strip().lower().replace('"', "").replace("'", "")
    return label if label in DOC_TYPES else "unknown"


# STEP 3 — EXTRACTOR SUB-AGENT

def _extract(text: str, doc_type: str, path: str) -> dict:
    """
    Ask the LLM to extract structured fields from the document text.
    Uses saved prompt improvements from feedback_agent if available.
    """
    extra_hint = _load_prompt_hints(doc_type)

    prompt = f"""
You are a CPA assistant specialising in logistics documents.

Extract the following fields from the {doc_type} document below.
If a field is not found, use null.

Fields to extract:
- shipper         (company name of sender)
- consignee       (company name of recipient)
- origin_port     (city or port where shipment started)
- destination_port(city or port where shipment ends)
- container_type  (e.g. 20ft, 40ft, LCL, FCL)
- weight_kg       (numeric, kilograms)
- total_cost      (numeric, amount charged)
- currency        (3-letter code, e.g. USD, EUR)
- invoice_date    (YYYY-MM-DD format)

{extra_hint}

Respond ONLY with a valid JSON object. No explanation, no markdown.

--- DOCUMENT START ---
{text[:3000]}
--- DOCUMENT END ---
""".strip()

    result = ask_llm_json(prompt)

    # Normalise keys and types
    cleaned = {}
    for field in EXTRACT_FIELDS:
        val = result.get(field)
        if field in ("total_cost", "weight_kg") and val is not None:
            try:
                val = float(str(val).replace(",", "").replace("$", "").strip())
            except (ValueError, TypeError):
                val = None
        cleaned[field] = val

    return cleaned


# PROMPT MEMORY (written by feedback_agent)

def _load_prompt_hints(doc_type: str) -> str:
    """Load any extra extraction hints saved by the feedback agent."""
    try:
        memory_path = Path(PROMPT_MEMORY)
        if not memory_path.exists():
            return ""
        with open(memory_path) as f:
            memory = json.load(f)
        hints = memory.get(doc_type, [])
        if hints:
            hint_text = "\n".join(f"- {h}" for h in hints)
            return f"Additional hints learned from previous runs:\n{hint_text}"
    except Exception:
        pass
    return ""
