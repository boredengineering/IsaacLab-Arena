# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""MCP Server for NVIDIA SimReady Central Asset Integration.

Provides Model Context Protocol (MCP) tool bindings to search, inspect,
download, and register SimReady USD assets into IsaacLab-Arena.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from isaaclab_arena.agentic_environment_generation.simready_central.client import (
    SimReadyCentralClient,
)

TOOL_DEFINITIONS = [
    {
        "name": "simready_search",
        "description": "Search NVIDIA SimReady Central via DeepSearch hybrid text + SigLIP2 vectors or OEM submission catalogs for production robotics USD assets (e.g., 'desk drawer', 'microwave', 'fr3', 'gripper').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search prompt or asset keywords.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter (e.g. 'furniture', 'appliance', 'tool').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of asset results to return (default: 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "simready_get_manifest",
        "description": "Retrieve the SimReady package BOM, license, and metadata manifest (com.nvidia.simready.packaging.json) for a given asset URL or package ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_url": {
                    "type": "string",
                    "description": "HTTPS URL pointing to the com.nvidia.simready.packaging.json file.",
                }
            },
            "required": ["manifest_url"],
        },
    },
    {
        "name": "simready_download",
        "description": "Download a SimReady USD stage and its metadata into the local IsaacLab-Arena asset cache for simulation and affordance introspection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_url": {
                    "type": "string",
                    "description": "Hugging Face resolve URL to the .usd or .usdc stage file.",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Optional local filename to assign to the downloaded stage.",
                },
                "target_dir": {
                    "type": "string",
                    "description": "Optional target directory (defaults to artifacts/assets/simready/).",
                },
            },
            "required": ["asset_url"],
        },
    },
    {
        "name": "simready_list_oem_submissions",
        "description": "List verified SimReady submissions from leading robotics OEMs (e.g. 'nvidia', 'frankarobotics', 'Robotiq-Official', 'FANUC-CORPORATION').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "oem": {
                    "type": "string",
                    "description": "OEM or creator namespace (e.g. 'nvidia', 'frankarobotics', 'Robotiq-Official').",
                    "default": "nvidia",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of submission records to return (default: 10).",
                    "default": 10,
                },
            },
        },
    },
]


class SimReadyMCPServer:
    """Stdio JSON-RPC 2.0 MCP server for SimReady Central."""

    def __init__(self, client: SimReadyCentralClient | None = None):
        self.client = client or SimReadyCentralClient()

    def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate client method."""
        try:
            if name == "simready_search":
                query = arguments.get("query", "")
                category = arguments.get("category")
                limit = int(arguments.get("limit", 5))
                hits = self.client.search_hybrid(query=query, limit=limit, category=category)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps([h.to_dict() for h in hits], indent=2),
                        }
                    ]
                }
            elif name == "simready_get_manifest":
                manifest_url = arguments.get("manifest_url", "")
                data = self.client.get_package_manifest(manifest_url)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(data, indent=2),
                        }
                    ]
                }
            elif name == "simready_download":
                asset_url = arguments.get("asset_url", "")
                asset_name = arguments.get("asset_name")
                target_dir = arguments.get("target_dir")
                dest = self.client.download_asset(
                    asset_url=asset_url, asset_name=asset_name, target_dir=target_dir
                )
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "status": "success",
                                    "saved_path": str(dest),
                                    "file_size_bytes": dest.stat().st_size,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }
            elif name == "simready_list_oem_submissions":
                oem = arguments.get("oem", "nvidia")
                limit = int(arguments.get("limit", 10))
                urls = self.client.get_oem_submissions(oem=oem)[:limit]
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "oem": oem,
                                    "count": len(urls),
                                    "submission_urls": urls,
                                },
                                indent=2,
                            ),
                        }
                    ]
                }
            else:
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                }
        except Exception as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Execution error in {name}: {str(e)}"}],
            }

    def run_stdio(self) -> None:
        """Run the JSON-RPC stdio protocol loop."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "simready-central",
                            "version": "1.0.0",
                        },
                    },
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": TOOL_DEFINITIONS},
                }
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                tool_result = self.handle_tool_call(tool_name, args)
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": tool_result,
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()


def main() -> None:
    """CLI entrypoint for testing and MCP stdio execution."""
    parser = argparse.ArgumentParser(description="SimReady Central MCP Server & CLI")
    parser.add_argument("--stdio", action="store_true", help="Run as MCP stdio server")
    parser.add_argument("--search", type=str, help="Execute hybrid search test")
    parser.add_argument("--oem", type=str, default="nvidia", help="OEM organization name")
    parser.add_argument("--list-submissions", action="store_true", help="List OEM submissions")
    args = parser.parse_args()

    client = SimReadyCentralClient()
    server = SimReadyMCPServer(client=client)

    if args.stdio:
        server.run_stdio()
    elif args.search:
        hits = client.search_hybrid(args.search, limit=5)
        print(f"Hits for '{args.search}': {len(hits)}")
        for h in hits:
            print(f"- [{h.score:.2f}] {h.name} ({h.id}) -> {h.download_url}")
    elif args.list_submissions:
        urls = client.get_oem_submissions(oem=args.oem)[:5]
        print(f"Top 5 submissions for {args.oem}:")
        for u in urls:
            print(f"  {u}")
    else:
        # Default: if run with no args and stdin is a pipe, run stdio; else print help
        if not sys.stdin.isatty():
            server.run_stdio()
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
