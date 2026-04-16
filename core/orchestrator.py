import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# HermesTool — mirrors Hermes Agent's tool schema

@dataclass
class HermesTool:
    """
    Represents a single agent wrapped as a Hermes-compatible tool.

    Attributes:
        name:        Unique short name used to call the tool.
        description: Human-readable description of what this tool does.
        parameters:  JSON-Schema-style dict describing the tool's inputs.
        fn:          The actual callable (agent's run() function or wrapper).
        result:      Populated after the tool runs (None before).
    """
    name:        str
    description: str
    parameters:  dict
    fn:          Callable
    result:      Any = field(default=None, repr=False)

    def __call__(self, **kwargs) -> Any:
        logger.info("[Hermes] Calling tool: %s", self.name)
        self.result = self.fn(**kwargs)
        return self.result

    def to_schema(self) -> dict:
        """Return a Hermes / OpenAI function-calling compatible schema dict."""
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.parameters,
            },
        }


# HermesOrchestrator — wraps all 7 agents as tools

class HermesOrchestrator:
    """
    Registers all 7 CWT CPA agents as Hermes tools and executes them
    in the correct pipeline order, passing outputs between tools.

    Args:
        source:   PDF source — "local" | "gdrive" | "gmail" | "all"
        dry_run:  If True, skip LLM + API calls (for testing structure only)
    """

    def __init__(self, source: str = "local", dry_run: bool = False):
        self.source  = source
        self.dry_run = dry_run

        # Lazy-import agents so this module can be imported independently
        from agents import (
            loader_agent,
            extractor_agent,
            dedup_agent,
            calculator_agent,
            freight_agent,
            report_agent,
            feedback_agent,
        )
        from core.db import init_db

        self._init_db = init_db
        self._extractor = extractor_agent   # kept for _parse_pdf access

        # Register tools in pipeline execution order
        self._tools: dict[str, HermesTool] = {}

        self._register(HermesTool(
            name="loader",
            description=(
                "Agent 1 — Loads PDF documents from a chosen source "
                "(local folder, Google Drive, or Gmail attachments). "
                "Returns a list of local file paths ready for extraction."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["local", "gdrive", "gmail", "all"],
                        "description": "Where to load PDFs from",
                    }
                },
                "required": ["source"],
            },
            fn=lambda source: loader_agent.run(source=source),
        ))

        self._register(HermesTool(
            name="extractor",
            description=(
                "Agent 2 — Classifies each PDF document type (invoice, "
                "bill_of_lading, freight_quote, customs_doc) then uses "
                "Docling + LLM to extract 9 structured logistics fields."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pdf_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of local PDF file paths to process",
                    }
                },
                "required": ["pdf_paths"],
            },
            fn=lambda pdf_paths: extractor_agent.run(pdf_paths),
        ))

        self._register(HermesTool(
            name="feedback",
            description=(
                "Agent 7 (Hermes Feedback Loop) — Identifies missing critical "
                "fields in extracted records, re-extracts them with improved "
                "targeted prompts, and saves successful hint patterns to "
                "prompt_memory.json for future runs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "extracted_records": {
                        "type": "array",
                        "description": "Records from extractor_agent.run()",
                    },
                    "raw_texts": {
                        "type": "object",
                        "description": "Dict mapping file path → raw PDF text",
                    },
                },
                "required": ["extracted_records", "raw_texts"],
            },
            fn=lambda extracted_records, raw_texts: feedback_agent.run(
                extracted_records, raw_texts
            ),
        ))

        self._register(HermesTool(
            name="dedup",
            description=(
                "Agent 3 — Prevents duplicate records from being stored. "
                "Uses a composite key (shipper + invoice_date + total_cost) "
                "to detect and skip duplicates before DB insertion."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "extracted_records": {
                        "type": "array",
                        "description": "Improved records from feedback_agent.run()",
                    }
                },
                "required": ["extracted_records"],
            },
            fn=lambda extracted_records: dedup_agent.run(extracted_records),
        ))

        self._register(HermesTool(
            name="calculator",
            description=(
                "Agent 4 — Calculates shipping cost analytics from all "
                "saved shipments: overall average, per-route averages, "
                "per-container-type averages, monthly trend, and "
                "most/cheapest routes."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            fn=lambda: calculator_agent.run(),
        ))

        self._register(HermesTool(
            name="freight",
            description=(
                "Agent 5 — Fetches current ocean freight market rates "
                "(5-level waterfall: Shiply/Apify → FBX Web Scraper → "
                "Xeneta Web Scraper → FBX API → FBX Static). "
                "Compares against your actual costs and flags anomalies "
                "(OVERPAYING / UNDERPAYING)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "calc_results": {
                        "type": "object",
                        "description": "Output dict from calculator_agent.run()",
                    }
                },
                "required": ["calc_results"],
            },
            fn=lambda calc_results: freight_agent.run(calc_results),
        ))

        self._register(HermesTool(
            name="report",
            description=(
                "Agent 6 — Generates full CPA reports in TXT and HTML formats, "
                "including KPI cards, cost-per-route tables, market comparison "
                "with colour-coded anomaly cards, monthly trend analysis, "
                "FBX/Xeneta rate sources, and an LLM executive summary."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dedup_summary":   {"type": "object"},
                    "calc_results":    {"type": "object"},
                    "freight_results": {"type": "object"},
                },
                "required": ["dedup_summary", "calc_results", "freight_results"],
            },
            fn=lambda dedup_summary, calc_results, freight_results: report_agent.run(
                dedup_summary=dedup_summary,
                calc_results=calc_results,
                freight_results=freight_results,
            ),
        ))

    # Public API

    def run_pipeline(self) -> dict:
        """
        Execute all 7 agents in pipeline order.
        Returns a dict with all intermediate and final results.
        """
        logger.info("[Hermes] Starting pipeline (source=%s, dry_run=%s)",
                    self.source, self.dry_run)

        self._init_db()

        # Step 1: Load
        pdf_paths = self.run_tool("loader", source=self.source)
        if not pdf_paths:
            logger.error("[Hermes] No PDFs found — aborting pipeline.")
            return {"error": "No PDFs found", "step": "loader"}

        # Step 2: Extract
        extracted_records = self.run_tool("extractor", pdf_paths=pdf_paths)
        if not extracted_records:
            logger.error("[Hermes] Extraction returned no records — aborting.")
            return {"error": "Extraction returned no records", "step": "extractor"}

        # Step 3: Feedback (Hermes loop)
        raw_texts = {
            path: self._extractor._parse_pdf(path)
            for path in pdf_paths
        }
        improved_records = self.run_tool(
            "feedback",
            extracted_records=extracted_records,
            raw_texts=raw_texts,
        )

        # Step 4: Dedup + Save
        dedup_summary = self.run_tool("dedup", extracted_records=improved_records)

        # Step 5: Calculate
        calc_results = self.run_tool("calculator")

        # Step 6: Market Rates
        freight_results = self.run_tool("freight", calc_results=calc_results)

        # Step 7: Report
        report_path = self.run_tool(
            "report",
            dedup_summary=dedup_summary,
            calc_results=calc_results,
            freight_results=freight_results,
        )

        logger.info("[Hermes] Pipeline complete. Report: %s", report_path)
        return {
            "pdf_paths":        pdf_paths,
            "extracted":        len(extracted_records),
            "improved":         len(improved_records),
            "dedup_summary":    dedup_summary,
            "calc_results":     calc_results,
            "freight_results":  freight_results,
            "report_path":      report_path,
        }

    def run_tool(self, name: str, **kwargs) -> Any:
        """
        Run a single registered tool by name.

        Args:
            name:   Tool name (e.g. "loader", "calculator", "report")
            kwargs: Arguments forwarded to the tool function.

        Returns:
            The tool's return value.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(
                f"Unknown tool '{name}'. Available: {list(self._tools.keys())}"
            )
        return tool(**kwargs)

    def list_tools(self) -> list[dict]:
        """Return all registered tool schemas (Hermes / OpenAI format)."""
        return [t.to_schema() for t in self._tools.values()]

    def tool_names(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self._tools.keys())

    # Internal

    def _register(self, tool: HermesTool):
        """Add a tool to the registry."""
        self._tools[tool.name] = tool
        logger.debug("[Hermes] Registered tool: %s", tool.name)
