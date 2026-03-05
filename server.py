"""
BigSolDB MCP Server
Exposes BigSolDB v2.1 solubility data via Model Context Protocol (SSE transport).

Usage:
    python server.py --csv /path/to/BigSolDBv2_1.csv --port 8000
"""

import argparse
import asyncio
import csv
import json
import math
import os
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DB: list[dict] = []


def load_db(csv_path: str) -> None:
    global DB
    print(f"Loading BigSolDB from {csv_path} …")
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # cast numerics
            for key in ("Temperature_K", "Solubility(mole_fraction)",
                        "Solubility(mol/L)", "LogS(mol/L)"):
                try:
                    row[key] = float(row[key])
                except (ValueError, KeyError):
                    row[key] = None
            DB.append(row)
    print(f"Loaded {len(DB):,} records.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def safe_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def record_to_dict(row: dict) -> dict:
    return {
        "smiles_solute":       row.get("SMILES_Solute"),
        "compound_name":       row.get("Compound_Name"),
        "cas":                 row.get("CAS"),
        "pubchem_cid":         row.get("PubChem_CID"),
        "fda_approved":        row.get("FDA_Approved"),
        "solvent":             row.get("Solvent"),
        "smiles_solvent":      row.get("SMILES_Solvent"),
        "temperature_K":       safe_float(row.get("Temperature_K")),
        "solubility_mole_fraction": safe_float(row.get("Solubility(mole_fraction)")),
        "solubility_mol_L":    safe_float(row.get("Solubility(mol/L)")),
        "logS_mol_L":          safe_float(row.get("LogS(mol/L)")),
        "source_doi":          row.get("Source"),
    }


def fmt_results(records: list[dict], limit: int = 50) -> str:
    total = len(records)
    shown = records[:limit]
    out = [f"Found {total} record(s) (showing up to {limit}):\n"]
    for i, r in enumerate(shown, 1):
        out.append(
            f"{i}. {r.get('compound_name') or r.get('smiles_solute')} | "
            f"Solvent: {r.get('solvent')} | "
            f"T={r.get('temperature_K')} K | "
            f"LogS={r.get('logS_mol_L'):.3f} | "
            f"Solubility={r.get('solubility_mol_L')} mol/L | "
            f"FDA={r.get('fda_approved')} | "
            f"DOI: {r.get('source_doi')}"
        )
    if total > limit:
        out.append(f"\n… and {total - limit} more records.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp_server = Server("bigsoldb")


@mcp_server.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[

        Tool(
            name="search_by_name",
            description=(
                "Search BigSolDB by compound name (case-insensitive substring match). "
                "Returns solubility records with temperature, solvent, LogS, and DOI."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Compound name or substring, e.g. 'naproxen', 'caffeine'"
                    },
                    "solvent": {
                        "type": "string",
                        "description": "Optional: filter by solvent name, e.g. 'water', 'ethanol'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max records to return (default 50)",
                        "default": 50
                    }
                },
                "required": ["name"]
            }
        ),

        Tool(
            name="search_by_smiles",
            description=(
                "Search BigSolDB by exact SMILES of the solute. "
                "Returns all solubility measurements for that compound across solvents and temperatures."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "smiles": {
                        "type": "string",
                        "description": "Exact SMILES string of the solute"
                    },
                    "solvent": {
                        "type": "string",
                        "description": "Optional: filter by solvent name"
                    }
                },
                "required": ["smiles"]
            }
        ),

        Tool(
            name="search_by_cas",
            description="Search BigSolDB by CAS registry number.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cas": {
                        "type": "string",
                        "description": "CAS number, e.g. '58-08-2' for caffeine"
                    }
                },
                "required": ["cas"]
            }
        ),

        Tool(
            name="search_by_solvent",
            description=(
                "Get all solubility records for a given solvent. "
                "Useful for solvent-centric analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "solvent": {
                        "type": "string",
                        "description": "Solvent name, e.g. 'water', 'acetone', 'ethanol'"
                    },
                    "min_logS": {
                        "type": "number",
                        "description": "Optional: minimum LogS(mol/L) filter"
                    },
                    "max_logS": {
                        "type": "number",
                        "description": "Optional: maximum LogS(mol/L) filter"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max records to return (default 50)"
                    }
                },
                "required": ["solvent"]
            }
        ),

        Tool(
            name="get_solubility_stats",
            description=(
                "Get summary statistics (mean, min, max, std LogS) for a compound "
                "across all solvents or a specific solvent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Compound name (substring match)"
                    },
                    "solvent": {
                        "type": "string",
                        "description": "Optional: restrict stats to one solvent"
                    }
                },
                "required": ["name"]
            }
        ),

        Tool(
            name="list_solvents",
            description="List all unique solvents available in BigSolDB.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        Tool(
            name="search_fda_approved",
            description=(
                "Return solubility records for FDA-approved compounds only. "
                "Optionally filter by solvent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "solvent": {
                        "type": "string",
                        "description": "Optional: filter by solvent name"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max records to return (default 50)"
                    }
                }
            }
        ),
    ])


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:

    def text(s: str) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=s)])

    # ---- search_by_name ----
    if name == "search_by_name":
        query = arguments["name"].lower()
        solvent_filter = arguments.get("solvent", "").lower()
        limit = int(arguments.get("limit", 50))

        results = [
            record_to_dict(r) for r in DB
            if query in (r.get("Compound_Name") or "").lower()
            and (not solvent_filter or solvent_filter in (r.get("Solvent") or "").lower())
        ]
        if not results:
            return text(f"No records found for name '{arguments['name']}'.")
        return text(fmt_results(results, limit))

    # ---- search_by_smiles ----
    elif name == "search_by_smiles":
        smiles = arguments["smiles"].strip()
        solvent_filter = arguments.get("solvent", "").lower()

        results = [
            record_to_dict(r) for r in DB
            if r.get("SMILES_Solute", "").strip() == smiles
            and (not solvent_filter or solvent_filter in (r.get("Solvent") or "").lower())
        ]
        if not results:
            return text(f"No records found for SMILES '{smiles}'.")
        return text(fmt_results(results, 100))

    # ---- search_by_cas ----
    elif name == "search_by_cas":
        cas = arguments["cas"].strip()
        results = [record_to_dict(r) for r in DB if r.get("CAS", "").strip() == cas]
        if not results:
            return text(f"No records found for CAS '{cas}'.")
        return text(fmt_results(results, 100))

    # ---- search_by_solvent ----
    elif name == "search_by_solvent":
        solvent = arguments["solvent"].lower()
        min_logS = safe_float(arguments.get("min_logS"))
        max_logS = safe_float(arguments.get("max_logS"))
        limit = int(arguments.get("limit", 50))

        results = []
        for r in DB:
            if solvent not in (r.get("Solvent") or "").lower():
                continue
            logS = safe_float(r.get("LogS(mol/L)"))
            if min_logS is not None and (logS is None or logS < min_logS):
                continue
            if max_logS is not None and (logS is None or logS > max_logS):
                continue
            results.append(record_to_dict(r))

        if not results:
            return text(f"No records found for solvent '{arguments['solvent']}'.")
        return text(fmt_results(results, limit))

    # ---- get_solubility_stats ----
    elif name == "get_solubility_stats":
        query = arguments["name"].lower()
        solvent_filter = arguments.get("solvent", "").lower()

        logS_values = []
        names_found = set()
        for r in DB:
            if query not in (r.get("Compound_Name") or "").lower():
                continue
            if solvent_filter and solvent_filter not in (r.get("Solvent") or "").lower():
                continue
            v = safe_float(r.get("LogS(mol/L)"))
            if v is not None:
                logS_values.append(v)
            names_found.add(r.get("Compound_Name", ""))

        if not logS_values:
            return text(f"No numeric LogS data found for '{arguments['name']}'.")

        n = len(logS_values)
        mean = sum(logS_values) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in logS_values) / n)
        out = (
            f"Stats for '{arguments['name']}'"
            + (f" in solvent '{arguments['solvent']}'" if solvent_filter else "")
            + f":\n"
            f"  Matched names: {', '.join(sorted(names_found))}\n"
            f"  N records: {n}\n"
            f"  LogS mean:  {mean:.3f}\n"
            f"  LogS std:   {std:.3f}\n"
            f"  LogS min:   {min(logS_values):.3f}\n"
            f"  LogS max:   {max(logS_values):.3f}\n"
        )
        return text(out)

    # ---- list_solvents ----
    elif name == "list_solvents":
        solvents = sorted(set(r.get("Solvent", "") for r in DB if r.get("Solvent")))
        return text(f"BigSolDB contains {len(solvents)} unique solvents:\n" + "\n".join(solvents))

    # ---- search_fda_approved ----
    elif name == "search_fda_approved":
        solvent_filter = arguments.get("solvent", "").lower()
        limit = int(arguments.get("limit", 50))

        results = [
            record_to_dict(r) for r in DB
            if (r.get("FDA_Approved") or "").strip().lower() == "yes"
            and (not solvent_filter or solvent_filter in (r.get("Solvent") or "").lower())
        ]
        if not results:
            return text("No FDA-approved records found with the given filters.")
        return text(fmt_results(results, limit))

    else:
        return text(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Starlette / SSE app
# ---------------------------------------------------------------------------

def make_app() -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1],
                mcp_server.create_initialization_options()
            )

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BigSolDB MCP Server")
    parser.add_argument(
        "--csv",
        default=os.getenv("BIGSOLDB_CSV", "BigSolDBv2_1.csv"),
        help="Path to BigSolDBv2_1.csv"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    load_db(args.csv)
    app = make_app()
    print(f"BigSolDB MCP server running at http://{args.host}:{args.port}/sse")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
