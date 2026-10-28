"""Agent-facing orchestration helpers.

The built-in orchestrator coordinates workflows. Optional Agno integration
lives under ``event_seo_mcp.integrations.agno`` and soft-fails when unavailable.
"""

from event_seo_mcp.orchestration.orchestrator import Orchestrator

__all__ = ["Orchestrator"]
