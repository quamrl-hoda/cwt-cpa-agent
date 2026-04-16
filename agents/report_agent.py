import json
import logging
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.db import fetch_all_shipments, fetch_market_rates, fetch_anomalies, fetch_agent_logs, log_agent
from core.config import OUTPUT_DIR

logger = logging.getLogger(__name__)
AGENT_NAME = "report_agent"


#  PUBLIC ENTRY POINT  

def run(
    dedup_summary:   dict,
    calc_results:    dict,
    freight_results: dict,
) -> str:
    """
    Generate full CPA reports (TXT + HTML).

    Returns:
        Path to the saved HTML report file.
    """
    logger.info("[Agent 6] Generating reports...")

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    #  LLM executive summary (shared by both formats)  
    llm_summary = _build_llm_summary(calc_results, freight_results)

    #  TXT report  
    txt_path = Path(OUTPUT_DIR) / f"cwt_cpa_report_{timestamp}.txt"
    txt = _build_txt_report(timestamp, dedup_summary, calc_results, freight_results, llm_summary)
    txt_path.write_text(txt, encoding="utf-8")
    logger.info("[Agent 6] TXT saved: %s", txt_path)

    # Print brief summary to console
    anomaly_count = len(freight_results.get("anomalies", []))
    print(f"\n{'='*60}")
    print(f"  REPORT COMPLETE — {timestamp}")
    print(f"  TXT   : {txt_path}")
    print(f"  Anomalies found: {anomaly_count}")
    print(f"{'='*60}\n")

    return str(txt_path)


#  LLM EXECUTIVE SUMMARY  

def _build_llm_summary(calc_results: dict, freight_results: dict) -> str:
    data = json.dumps({
        "overall_avg_cost":     calc_results.get("overall_avg_cost"),
        "avg_cost_per_route":   calc_results.get("avg_cost_per_route"),
        "monthly_trend":        calc_results.get("monthly_trend", {}).get("trend_direction"),
        "most_expensive_route": calc_results.get("most_expensive_route"),
        "cheapest_route":       calc_results.get("cheapest_route"),
        "anomalies":            freight_results.get("anomalies", []),
        "fbx_rates":            freight_results.get("fbx_rates", {}),
        "market_comparisons":   freight_results.get("comparisons", []),
    }, indent=2)

    prompt = f"""
You are a senior CPA specialising in international logistics cost control.

Given the following shipping cost analytics, market comparisons, and anomalies,
write a concise professional executive summary (150–250 words) that:
1. States the overall cost performance briefly
2. Highlights the top 1-2 anomalies and what they mean financially
3. Notes the market rate context (FBX/Shiply data used)
4. Gives 3 concrete, actionable recommendations to reduce costs
5. Uses professional financial language suitable for a board-level report

Data:
{data}
""".strip()

    text = ask_llm(prompt, temperature=0.3, max_tokens=500)
    # Guard against LLM error strings
    if text.startswith("ERROR:"):
        logger.warning("LLM executive summary failed: %s", text)
        return "Executive summary could not be generated — see data sections above."
    return text


#  PLAIN-TEXT REPORT  

def _build_txt_report(
    timestamp: str,
    dedup_summary: dict,
    calc_results: dict,
    freight_results: dict,
    llm_summary: str,
) -> str:
    W = 70
    pipeline_sec  = _txt_agent_pipeline(dedup_summary)
    classif_sec   = _txt_classification_summary()
    feedback_sec  = _txt_feedback_summary()

    sections = [s for s in [
        _txt_header(timestamp, W),
        pipeline_sec,
        classif_sec,
        _txt_ingestion(dedup_summary),
        _txt_cost_analytics(calc_results),
        _txt_market_comparison(freight_results),
        _txt_anomalies(freight_results),
        feedback_sec,
         "\n SECTION 6: Summary (AI)\n"  + "\n\n" + llm_summary
    ] if s]
    return "\n\n".join(sections)


def _txt_header(ts: str, W: int) -> str:
    return (
        f"CROWD WISDOM TRADING — CPA Logistics Cost Report\n"
        f"Generated: " + ts
    )


def _txt_ingestion(d: dict) -> str:
    lines = [
        " SECTION 1: Data Ingestion  ",
        f"  Documents processed : {d.get('total_input', 0)}",
        f"  Saved to DB         : {d.get('saved', 0)}",
        f"  Duplicates skipped  : {d.get('skipped', 0)}",
        f"  Failed/incomplete   : {d.get('failed', 0)}",
    ]
    for f in d.get("failed_records", []):
        lines.append(f"    • {f.get('file','?')} — {f.get('reason','?')}")
    return "\n".join(lines)


def _txt_cost_analytics(r: dict) -> str:
    if "error" in r:
        return f" SECTION 2: Cost Analytics \n  {r['error']}"
    lines = [
        " SECTION 2: Cost Analytics ",
        f"  Total shipments : {r.get('total_shipments', 0)}",
        f"  Overall avg cost: ${r.get('overall_avg_cost', 0):,.2f}",
        "",
        "  Avg cost per route:",
    ]
    for route, avg in (r.get("avg_cost_per_route") or {}).items():
        lines.append(f"    {route:<38} ${avg:>10,.2f}")
    trend = r.get("monthly_trend", {})
    lines += ["", f"  Trend: {trend.get('trend_direction', 'n/a')}"]
    for month, avg in (trend.get("by_month") or {}).items():
        lines.append(f"    {month}   ${avg:,.2f}")
    return "\n".join(lines)


def _txt_market_comparison(r: dict) -> str:
    comps = r.get("comparisons", [])
    if not comps:
        return " SECTION 3: Market Comparison \n  No market data available."
    lines = [
        " SECTION 3: Market Comparison (Shiply / FBX) ",
        f"  {'Route':<35} {'Your Avg':>9} {'Market':>9} {'Diff':>8} {'%':>6}  Source",
        "  " + "-" * 80,
    ]
    for c in comps:
        market = f"${c['market_rate']:>8,.2f}" if c["market_rate"] else "      N/A"
        diff   = f"${c['difference']:>+8,.2f}" if c["difference"] is not None else "       N/A"
        pct    = f"{c.get('pct_diff',0):>+5.1f}%" if c["difference"] is not None else "   N/A"
        flag   = " (!)" if (c.get("overpaying") and (c.get("pct_diff") or 0) >= 20) else ""
        src    = c.get("rate_source", "")
        lines.append(
            f"  {c['route']:<35} ${c['your_avg_usd']:>8,.2f} {market} {diff} {pct}{flag}  {src}"
        )
    return "\n".join(lines)


def _txt_anomalies(r: dict) -> str:
    anomalies = r.get("anomalies", [])
    if not anomalies:
        return " SECTION 4: Anomalies \n  No anomalies detected."
    lines = [f" SECTION 4: Anomalies ({len(anomalies)} found) "]
    for i, a in enumerate(anomalies, 1):
        lines += [
            f"\n  [{i}] [{a.get('severity','?')}] {a['type']}",
            f"      Route  : {a['route']}",
            f"      Detail : {a['message']}",
        ]
    return "\n".join(lines)


#  AGENT PIPELINE + FEEDBACK + CLASSIFICATION SECTIONS  

def _txt_agent_pipeline(dedup_summary: dict) -> str:
    """Section: 7-agent pipeline architecture table."""
    W = 70
    lines = [
       
        " MULTI-AGENT PIPELINE ARCHITECTURE",

        "  Pipeline mode: Hermes Orchestrator (sequential tool-calling)",
       
        "  #   Agent                   Responsibility         ",

        "  1   IngestionAgent          Loads PDFs: local / GDrive / Gmail   ",
        "  2   ExtractionAgent         Classifies + extracts 9 fields (LLM) ",
        "  3   FeedbackAgent           Hermes loop: re-extracts + hints     ",
        "  4   DedupAgent              Deduplication before DB insert       ",
        "  5   CalculatorAgent         Avg cost / route / trend analysis    ",
        "  6   MarketAgent             FBX / Xeneta rates + anomaly detect  ",
        "  7   ReportAgent             Generates TXT + HTML CPA report      ",
  
        "",
        f"  Documents : {dedup_summary.get('total_input', 0)} processed │ "
        f"{dedup_summary.get('saved', 0)} saved │ "
        f"{dedup_summary.get('skipped', 0)} dupes │ "
        f"{dedup_summary.get('failed', 0)} failed",
    ]
    return "\n".join(lines)


def _txt_classification_summary() -> str:
    """Section: Document classification breakdown from agent logs (Agent 2)."""
    try:
        logs = fetch_agent_logs("extractor_agent", limit=100)
    except Exception:
        return ""
    if not logs:
        return ""

    success = [l for l in logs if l.get("status") == "success"]
    skipped = [l for l in logs if l.get("status") == "skipped"]
    failed  = [l for l in logs if l.get("status") == "failure"]

    lines = [
        " DOCUMENT CLASSIFICATION (Agent 2 — ExtractionAgent) ",
        "  Supported types : invoice | bill_of_lading | freight_quote | customs_doc",
        f"  Successfully extracted : {len(success)}",
        f"  Skipped (unsupported)  : {len(skipped)}   ← classified as 'unknown'",
        f"  Parse failures         : {len(failed)}",
    ]
    return "\n".join(lines)


def _txt_feedback_summary() -> str:
    """Section: Hermes feedback loop results from agent logs (Agent 3)."""
    try:
        logs = fetch_agent_logs("feedback_agent", limit=100)
    except Exception:
        return ""
    if not logs:
        return ""

    successes = [l for l in logs if l.get("status") == "success"]
    failures  = [l for l in logs if l.get("status") == "failure"]

    lines = [
        " HERMES FEEDBACK LOOP (Agent 3 — FeedbackAgent) ",
        f"  Fields recovered via targeted re-extraction : {len(successes)}",
        f"  Fields still missing after re-extraction    : {len(failures)}",
        "  Prompt memory : core/prompt_memory.json (successful hints reused next run)",
    ]
    for s in successes[:3]:
        src   = s.get("source_file", "")
        fname = src.replace("\\", "/").split("/")[-1]
        lines.append(f"    ✔ {fname} — {s.get('message', '')}")
    for f in failures[:3]:
        src   = f.get("source_file", "")
        fname = src.replace("\\", "/").split("/")[-1]
        lines.append(f"    ✘ {fname} — {f.get('message', '')}")
    return "\n".join(lines)


