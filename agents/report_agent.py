"""
report_agent.py — Agent 6
==========================
Combines findings from all agents and generates:
  1. outputs/cwt_cpa_report_<timestamp>.txt  — plain-text report
  2. outputs/cwt_cpa_report_<timestamp>.html — rich HTML report (open in browser)

HTML report includes:
  - KPI cards (total docs, avg cost, anomalies)
  - Cost per route table
  - Market comparison table with colour-coded status
  - Anomaly cards with severity badges
  - Monthly cost trend
  - FBX rate sources used
  - LLM executive summary
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.db import fetch_all_shipments, fetch_market_rates, fetch_anomalies, log_agent
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

    #  HTML report  
    html_path = Path(OUTPUT_DIR) / f"cwt_cpa_report_{timestamp}.html"
    html = _build_html_report(timestamp, dedup_summary, calc_results, freight_results, llm_summary)
    html_path.write_text(html, encoding="utf-8")
    logger.info("[Agent 6] HTML saved: %s", html_path)

    log_agent(AGENT_NAME, "success", f"Reports saved — {html_path.name}")

    # Print brief summary to console
    anomaly_count = len(freight_results.get("anomalies", []))
    print(f"\n{'='*60}")
    print(f"  REPORT COMPLETE — {timestamp}")
    print(f"  HTML  : {html_path}")
    print(f"  TXT   : {txt_path}")
    print(f"  Anomalies found: {anomaly_count}")
    print(f"{'='*60}\n")

    return str(html_path)


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
    sections = [
        _txt_header(timestamp, W),
        _txt_ingestion(dedup_summary),
        _txt_cost_analytics(calc_results),
        _txt_market_comparison(freight_results),
        _txt_anomalies(freight_results),
        "━" * W + "\n SECTION 5: Executive Summary (AI)\n" + "━" * W + "\n\n" + llm_summary,
        "─" * W + "\nEnd of Report — CWT CPA Agent",
    ]
    return "\n\n".join(sections)


def _txt_header(ts: str, W: int) -> str:
    return (
        "╔" + "═" * (W - 2) + "╗\n"
        f"║{'CROWD WISDOM TRADING — CPA Logistics Cost Report':^{W-2}}║\n"
        f"║{'Generated: ' + ts:^{W-2}}║\n"
        "╚" + "═" * (W - 2) + "╝"
    )


def _txt_ingestion(d: dict) -> str:
    lines = [
        "━━━ SECTION 1: Data Ingestion ━━━",
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
        return f"━━━ SECTION 2: Cost Analytics ━━━\n  {r['error']}"
    lines = [
        "━━━ SECTION 2: Cost Analytics ━━━",
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
        return "━━━ SECTION 3: Market Comparison ━━━\n  No market data available."
    lines = [
        "━━━ SECTION 3: Market Comparison (Shiply / FBX) ━━━",
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
        return "━━━ SECTION 4: Anomalies ━━━\n  No anomalies detected."
    lines = [f"━━━ SECTION 4: Anomalies ({len(anomalies)} found) ━━━"]
    for i, a in enumerate(anomalies, 1):
        lines += [
            f"\n  [{i}] [{a.get('severity','?')}] {a['type']}",
            f"      Route  : {a['route']}",
            f"      Detail : {a['message']}",
        ]
    return "\n".join(lines)


#  HTML REPORT  

def _build_html_report(
    timestamp: str,
    dedup_summary: dict,
    calc_results: dict,
    freight_results: dict,
    llm_summary: str,
) -> str:
    comparisons   = freight_results.get("comparisons", [])
    anomalies     = freight_results.get("anomalies", [])
    avg_cost      = calc_results.get("overall_avg_cost", 0) or 0
    total_ships   = calc_results.get("total_shipments", 0)
    saved         = dedup_summary.get("saved", 0)
    skipped       = dedup_summary.get("skipped", 0)
    monthly_trend = calc_results.get("monthly_trend", {})
    trend_dir     = monthly_trend.get("trend_direction", "—")
    by_month      = monthly_trend.get("by_month", {})
    fbx_rates     = freight_results.get("fbx_rates", {})

    trend_color = "#10b981" if "decreas" in trend_dir else ("#ef4444" if "increas" in trend_dir else "#94a3b8")
    anomaly_count = len(anomalies)

    # KPI cards
    kpis_html = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Shipments</div>
        <div class="kpi-value">{total_ships}</div>
        <div class="kpi-sub">{saved} saved · {skipped} dupes</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Overall Avg Cost</div>
        <div class="kpi-value">${avg_cost:,.2f}</div>
        <div class="kpi-sub">per shipment (USD)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Cost Trend</div>
        <div class="kpi-value" style="color:{trend_color};font-size:1.4rem">{trend_dir}</div>
        <div class="kpi-sub">month-over-month</div>
      </div>
      <div class="kpi-card {'kpi-danger' if anomaly_count > 0 else ''}">
        <div class="kpi-label">Anomalies</div>
        <div class="kpi-value" style="{'color:#ef4444' if anomaly_count > 0 else ''}">{anomaly_count}</div>
        <div class="kpi-sub">{'requires attention' if anomaly_count > 0 else 'all clear'}</div>
      </div>
    </div>
    """

    # Route comparison table
    rows_html = ""
    for c in comparisons:
        market_disp = f"${c['market_rate']:,.2f}" if c["market_rate"] else "N/A"
        diff_disp   = f"${c['difference']:+,.2f}" if c["difference"] is not None else "N/A"
        pct_disp    = f"{c.get('pct_diff', 0):+.1f}%" if c["difference"] is not None else "N/A"
        src_disp    = c.get("rate_source", "—")
        fbx_disp    = c.get("fbx_code") or "—"

        if c.get("overpaying") and (c.get("pct_diff") or 0) >= 20:
            status_html = '<span class="badge badge-danger">OVERPAYING</span>'
            row_class   = "row-danger"
        elif c.get("overpaying") is False:
            status_html = '<span class="badge badge-success">UNDER MARKET</span>'
            row_class   = "row-success"
        else:
            status_html = '<span class="badge badge-neutral">N/A</span>'
            row_class   = ""

        rows_html += f"""
        <tr class="{row_class}">
          <td>{c['route']}</td>
          <td>${c['your_avg_usd']:,.2f}</td>
          <td>{market_disp}</td>
          <td>{diff_disp}</td>
          <td>{pct_disp}</td>
          <td>{fbx_disp}</td>
          <td>{src_disp}</td>
          <td>{status_html}</td>
        </tr>"""

    # Anomaly cards
    anomaly_html = ""
    for a in anomalies:
        sev = a.get("severity", "MEDIUM")
        sev_class = "anomaly-high" if sev == "HIGH" else ("anomaly-low" if sev == "LOW" else "anomaly-medium")
        anomaly_html += f"""
        <div class="anomaly-card {sev_class}">
          <div class="anomaly-header">
            <span class="severity-badge">{sev}</span>
            <span class="anomaly-type">{a['type']}</span>
          </div>
          <div class="anomaly-route">{a.get('route','—')}</div>
          <div class="anomaly-message">{a.get('message','')}</div>
          <div class="anomaly-meta">
            Your avg: <strong>${a.get('your_avg',0):,.2f}</strong> |
            Market: <strong>${a.get('market_rate',0):,.2f}</strong> |
            Diff: <strong>{a.get('pct_diff',0):+.1f}%</strong>
          </div>
        </div>"""

    if not anomaly_html:
        anomaly_html = '<div class="no-anomalies">&#10003; No anomalies detected across all routes.</div>'

    # Monthly trend table
    trend_rows = ""
    months = list(by_month.keys())
    for i, (month, avg) in enumerate(by_month.items()):
        prev_avg = list(by_month.values())[i - 1] if i > 0 else avg
        delta = avg - prev_avg
        arrow = "&#8679;" if delta > 0 else ("&#8681;" if delta < 0 else "&#8680;")
        color = "#ef4444" if delta > 0 else ("#10b981" if delta < 0 else "#94a3b8")
        trend_rows += f"""
        <tr>
          <td>{month}</td>
          <td>${avg:,.2f}</td>
          <td style="color:{color}">{arrow} ${abs(delta):,.2f}</td>
        </tr>"""

    # FBX sources used
    fbx_html = ""
    if fbx_rates:
        fbx_html = "<ul class='fbx-list'>"
        for route, rate in fbx_rates.items():
            fbx_html += f"<li><strong>{route}</strong>: ${rate:,.2f}</li>"
        fbx_html += "</ul>"
    else:
        fbx_html = "<p class='muted'>No FBX rate data fetched this run.</p>"

    # LLM summary — preserve newlines
    llm_html = llm_summary.replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CWT CPA Report — {timestamp}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --surface2: #22263a;
      --border: #2e3250;
      --text: #e2e8f0;
      --muted: #64748b;
      --accent: #6366f1;
      --accent2: #818cf8;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --info: #38bdf8;
    }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.6;
    }}
    .page-wrap {{ max-width: 1300px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}

    /* Header */
    .report-header {{
      background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2.5rem 2rem;
      margin-bottom: 2rem;
      position: relative;
      overflow: hidden;
    }}
    .report-header::before {{
      content: '';
      position: absolute; inset: 0;
      background: radial-gradient(ellipse at top right, rgba(99,102,241,0.25) 0%, transparent 70%);
    }}
    .report-header h1 {{
      font-size: 1.9rem;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.5px;
    }}
    .report-header .subtitle {{
      color: var(--accent2);
      margin-top: 0.4rem;
      font-size: 0.9rem;
    }}
    .report-header .timestamp {{
      position: absolute; top: 1.5rem; right: 2rem;
      background: rgba(99,102,241,0.2);
      border: 1px solid rgba(99,102,241,0.4);
      border-radius: 8px;
      padding: 0.3rem 0.8rem;
      font-size: 0.8rem;
      color: var(--accent2);
    }}

    /* KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1.2rem;
      margin-bottom: 2.5rem;
    }}
    .kpi-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.4rem 1.6rem;
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .kpi-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
    .kpi-card.kpi-danger {{ border-color: rgba(239,68,68,0.5); background: rgba(239,68,68,0.07); }}
    .kpi-label {{ font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; }}
    .kpi-value {{ font-size: 2rem; font-weight: 700; color: var(--text); margin: 0.4rem 0 0.2rem; }}
    .kpi-sub {{ font-size: 0.78rem; color: var(--muted); }}

    /* Sections */
    .section {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.8rem 2rem;
      margin-bottom: 2rem;
    }}
    .section-title {{
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--accent2);
      margin-bottom: 1.4rem;
      padding-bottom: 0.8rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}
    .section-title .icon {{ font-size: 1.1rem; }}

    /* Tables */
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ background: var(--surface2); color: var(--muted); font-size: 0.75rem;
          text-transform: uppercase; letter-spacing: 0.7px;
          padding: 0.7rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }}
    td {{ padding: 0.65rem 1rem; border-bottom: 1px solid var(--border); color: var(--text); }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--surface2); }}
    .row-danger td {{ background: rgba(239,68,68,0.06); }}
    .row-success td {{ background: rgba(16,185,129,0.06); }}

    /* Badges */
    .badge {{
      display: inline-block; padding: 0.2rem 0.6rem;
      border-radius: 999px; font-size: 0.7rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.5px;
    }}
    .badge-danger  {{ background: rgba(239,68,68,0.2);   color: #fca5a5; }}
    .badge-success {{ background: rgba(16,185,129,0.2);  color: #6ee7b7; }}
    .badge-neutral {{ background: rgba(148,163,184,0.15); color: #94a3b8; }}

    /* Anomaly cards */
    .anomaly-cards {{ display: flex; flex-direction: column; gap: 1rem; }}
    .anomaly-card {{
      border-radius: 10px;
      padding: 1.2rem 1.4rem;
      border-left: 4px solid;
    }}
    .anomaly-high   {{ border-color: #ef4444; background: rgba(239,68,68,0.08); }}
    .anomaly-medium {{ border-color: #f59e0b; background: rgba(245,158,11,0.08); }}
    .anomaly-low    {{ border-color: #38bdf8; background: rgba(56,189,248,0.08); }}
    .anomaly-header {{ display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.4rem; }}
    .anomaly-type {{ font-weight: 700; font-size: 0.95rem; }}
    .severity-badge {{
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      background: rgba(239,68,68,0.25);
      color: #fca5a5;
    }}
    .anomaly-high .severity-badge {{ background: rgba(239,68,68,0.25); color: #fca5a5; }}
    .anomaly-medium .severity-badge {{ background: rgba(245,158,11,0.25); color: #fcd34d; }}
    .anomaly-low .severity-badge {{ background: rgba(56,189,248,0.25); color: #7dd3fc; }}
    .anomaly-route {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 0.4rem; }}
    .anomaly-message {{ font-size: 0.88rem; margin-bottom: 0.5rem; }}
    .anomaly-meta {{ font-size: 0.8rem; color: var(--muted); }}
    .no-anomalies {{
      padding: 2rem;
      text-align: center;
      color: var(--success);
      border: 1px dashed rgba(16,185,129,0.3);
      border-radius: 8px;
      font-size: 1rem;
    }}

    /* Executive summary */
    .exec-summary {{
      font-size: 0.92rem;
      line-height: 1.8;
      color: var(--text);
      background: var(--surface2);
      border-radius: 8px;
      padding: 1.4rem;
      border-left: 4px solid var(--accent);
    }}

    /* FBX list */
    .fbx-list {{ list-style: none; display: flex; flex-wrap: wrap; gap: 0.6rem; }}
    .fbx-list li {{
      background: rgba(99,102,241,0.12);
      border: 1px solid rgba(99,102,241,0.3);
      border-radius: 6px;
      padding: 0.3rem 0.8rem;
      font-size: 0.8rem;
    }}

    .muted {{ color: var(--muted); font-size: 0.85rem; }}
    .footer {{
      text-align: center;
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 3rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>
<div class="page-wrap">

  <!-- Header -->
  <div class="report-header">
    <div class="timestamp">{timestamp}</div>
    <h1>CWT CPA Logistics Cost Report</h1>
    <div class="subtitle">Crowd Wisdom Trading · Automated Cost Performance Analysis</div>
  </div>

  <!-- KPI cards -->
  {kpis_html}

  <!-- Section 2: Cost Analytics -->
  <div class="section">
    <div class="section-title"><span class="icon">&#128200;</span> Cost Analytics</div>
    <table>
      <thead>
        <tr>
          <th>Route</th>
          <th>Avg Cost (USD)</th>
          <th>Shipment Count</th>
        </tr>
      </thead>
      <tbody>
        {''.join(
            f"<tr><td>{route}</td><td>${avg:,.2f}</td><td>—</td></tr>"
            for route, avg in (calc_results.get("avg_cost_per_route") or {}).items()
        )}
      </tbody>
    </table>
  </div>

  <!-- Section 3: Market Comparison -->
  <div class="section">
    <div class="section-title"><span class="icon">&#127760;</span> Market Rate Comparison (Shiply / FBX)</div>
    {f'''<table>
      <thead>
        <tr>
          <th>Route</th><th>Your Avg</th><th>Market Rate</th>
          <th>Difference</th><th>% Diff</th><th>FBX Code</th>
          <th>Source</th><th>Status</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>''' if comparisons else '<p class="muted">No market rate data was fetched this run.</p>'}
  </div>

  <!-- Section 4: Anomalies -->
  <div class="section">
    <div class="section-title"><span class="icon">&#128680;</span> Anomalies ({anomaly_count} found)</div>
    <div class="anomaly-cards">
      {anomaly_html}
    </div>
  </div>

  <!-- Section: Monthly Trend -->
  <div class="section">
    <div class="section-title"><span class="icon">&#128197;</span> Monthly Cost Trend</div>
    {f'''<table>
      <thead><tr><th>Month</th><th>Avg Cost (USD)</th><th>Change</th></tr></thead>
      <tbody>{trend_rows}</tbody>
    </table>''' if by_month else '<p class="muted">Not enough data for monthly trend.</p>'}
  </div>

  <!-- Section: FBX Market Rates Used -->
  <div class="section">
    <div class="section-title"><span class="icon">&#128674;</span> Freightos Baltic Index (FBX) Rates Used</div>
    {fbx_html}
  </div>

  <!-- Section 5: Executive Summary -->
  <div class="section">
    <div class="section-title"><span class="icon">&#129302;</span> AI Executive Summary</div>
    <div class="exec-summary">{llm_html}</div>
  </div>

  <div class="footer">
    Generated by CWT CPA Agent &mdash; {timestamp}
  </div>

</div>
</body>
</html>"""
