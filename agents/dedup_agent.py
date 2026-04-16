import logging
from core.db import record_exists, insert_shipment, log_agent

logger = logging.getLogger(__name__)
AGENT_NAME = "dedup_agent"


def run(extracted_records: list[dict]) -> dict:
    """
    For each extracted record:
      - If a matching record exists in DB → skip (duplicate)
      - If new → insert into DB

    Args:
        extracted_records: List of dicts from extractor_agent.run()

    Returns:
        Summary dict with saved, skipped, and failed counts + details.
    """
    saved   = []
    skipped = []
    failed  = []

    for record in extracted_records:
        source = record.get("source_file", "unknown")

        #   Reject documents explicitly skipped by the extractor  
        skip_reason = record.get("skip_reason")
        if skip_reason or record.get("doc_type") == "unknown":
            reason = skip_reason or "unsupported document type (classified as 'unknown')"
            logger.warning("  [Agent 3] Skipping %s — %s", source, reason)
            failed.append({"file": source, "reason": reason})
            log_agent(AGENT_NAME, "skipped", reason, source)
            continue

        #   Validate minimum required fields  
        shipper      = record.get("shipper") or ""
        invoice_date = record.get("invoice_date") or ""
        total_cost   = record.get("total_cost")

        if total_cost is None:
            logger.warning("  [Agent 3] Skipping %s — missing total_cost", source)
            failed.append({"file": source, "reason": "missing total_cost"})
            log_agent(AGENT_NAME, "failure", "missing total_cost", source)
            continue

        #   Dedup check  
        if record_exists(shipper, invoice_date, float(total_cost)):
            logger.info(" [Agent 3] Duplicate — skipping: %s", source)
            skipped.append(source)
            log_agent(AGENT_NAME, "skipped", "duplicate record", source)
            continue

        #   Insert new record  
        try:
            new_id = insert_shipment(record)
            saved.append({"id": new_id, "file": source})
            log_agent(AGENT_NAME, "success", f"Inserted as row id={new_id}", source)
            logger.info(" [Agent 3] Saved row id=%d from %s", new_id, source)
        except Exception as e:
            logger.error(" [Agent 3] Insert failed for %s: %s", source, e)
            failed.append({"file": source, "reason": str(e)})
            log_agent(AGENT_NAME, "failure", str(e), source)

    summary = {
        "total_input": len(extracted_records),
        "saved":       len(saved),
        "skipped":     len(skipped),
        "failed":      len(failed),
        "saved_records":   saved,
        "skipped_files":   skipped,
        "failed_records":  failed,
    }

    logger.info(
        " [Agent 3] Done — saved=%d  skipped=%d  failed=%d",
        summary["saved"], summary["skipped"], summary["failed"],
    )
    return summary
