"""
calculator_agent.py — Agent 4
Calculates shipping cost analytics from all saved shipments.

Metrics:
  - Average cost per route (origin → destination)
  - Average cost per container type
  - Most / cheapest route
  - Month-over-month trend
  - Overall average cost
"""

import logging
from collections import defaultdict
from core.db import fetch_all_shipments, log_agent

logger = logging.getLogger(__name__)
AGENT_NAME = "calculator_agent"


def run() -> dict:
    """
    Pull all shipments from DB and compute cost analytics.

    Returns:
        Dict with analytics results.
    """
    logger.info(" [Agent 4] Running cost calculations...")

    shipments = fetch_all_shipments()

    if not shipments:
        logger.warning(" [Agent 4] No shipments in DB yet.")
        log_agent(AGENT_NAME, "failure", "No shipments found in DB")
        return {"error": "No shipments found in DB"}

    #   Filter only records that have a cost  
    valid = [s for s in shipments if s.get("total_cost") is not None]
    logger.info("   Found %d valid shipments (of %d total)", len(valid), len(shipments))

    results = {
        "total_shipments":     len(shipments),
        "valid_for_calc":      len(valid),
        "overall_avg_cost":    _overall_avg(valid),
        "avg_cost_per_route":  _avg_by_route(valid),
        "avg_cost_per_container": _avg_by_container(valid),
        "most_expensive_route":  _extremes(valid, "max"),
        "cheapest_route":        _extremes(valid, "min"),
        "monthly_trend":         _monthly_trend(valid),
    }

    log_agent(AGENT_NAME, "success", f"Calculated stats for {len(valid)} shipments")
    logger.info(" [Agent 4] Calculations complete: %s", _summary_str(results))
    return results


# HELPERS FUNCTIONS
def _route_key(s: dict) -> str:
    origin = s.get("origin_port") or "Unknown"
    dest   = s.get("destination_port") or "Unknown"
    return f"{origin} → {dest}"


def _overall_avg(shipments: list[dict]) -> float:
    if not shipments:
        return 0.0
    total = sum(s["total_cost"] for s in shipments)
    return round(total / len(shipments), 2)


def _avg_by_route(shipments: list[dict]) -> dict:
    """Average cost grouped by origin→destination route."""
    route_costs = defaultdict(list)
    for s in shipments:
        route_costs[_route_key(s)].append(s["total_cost"])

    return {
        route: round(sum(costs) / len(costs), 2)
        for route, costs in sorted(route_costs.items())
    }


def _avg_by_container(shipments: list[dict]) -> dict:
    """Average cost grouped by container type."""
    container_costs = defaultdict(list)
    for s in shipments:
        ctype = (s.get("container_type") or "unknown").strip().lower()
        container_costs[ctype].append(s["total_cost"])

    return {
        ctype: round(sum(costs) / len(costs), 2)
        for ctype, costs in sorted(container_costs.items())
    }


def _extremes(shipments: list[dict], mode: str) -> dict:
    """Return the most expensive (max) or cheapest (min) route with its avg cost."""
    avg_by_route = _avg_by_route(shipments)
    if not avg_by_route:
        return {}

    if mode == "max":
        route = max(avg_by_route, key=avg_by_route.get)
    else:
        route = min(avg_by_route, key=avg_by_route.get)

    return {"route": route, "avg_cost_usd": avg_by_route[route]}


def _monthly_trend(shipments: list[dict]) -> dict:
    """
    Group costs by YYYY-MM and compute monthly averages.
    Shows direction of cost over time.
    """
    monthly = defaultdict(list)
    for s in shipments:
        date = s.get("invoice_date") or ""
        if len(date) >= 7:           # at least YYYY-MM
            month = date[:7]
            monthly[month].append(s["total_cost"])

    trend = {
        month: round(sum(costs) / len(costs), 2)
        for month, costs in sorted(monthly.items())
    }

    # Add direction label
    months = list(trend.keys())
    if len(months) >= 2:
        delta = trend[months[-1]] - trend[months[-2]]
        direction = "⬆ increasing" if delta > 0 else "⬇ decreasing" if delta < 0 else "→ stable"
    else:
        direction = "→ not enough data"

    return {"by_month": trend, "trend_direction": direction}


def _summary_str(results: dict) -> str:
    return (
        f"overall_avg=${results['overall_avg_cost']}  "
        f"routes={len(results['avg_cost_per_route'])}  "
        f"trend={results['monthly_trend'].get('trend_direction', 'n/a')}"
    )
