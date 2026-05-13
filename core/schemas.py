"""Structured outputs for tool-selection evaluation (LangChain-friendly Pydantic models)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolInvocation(BaseModel):
    """One tool call in a multi-tool plan."""

    tool_name: str = Field(description="Exact tool name from the provided catalog")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments matching that tool's parameter schema",
    )


class MultiToolSelection(BaseModel):
    """Expected JSON shape: all tools that apply to the user message, in suggested order."""

    tools: list[ToolInvocation] = Field(
        min_length=1,
        description="Ordered list of every catalog tool needed to satisfy the user request",
    )
    intent: str = Field(
        description="Short natural-language summary of what the user wants"
    )
    reasoning: str = Field(
        default="",
        description=(
            "Single-turn ReAct-style narrative: why these tools and order fit the user message "
            "(optional for backward compatibility; models should fill when prompted)"
        ),
    )
    steps: list[str] = Field(
        default_factory=list,
        description=(
            "Discrete thought lines (e.g. one string per Thought) before the final tool plan; "
            "optional; omit or [] if not used"
        ),
    )


# Backward-compatible name for single-tool docs / imports (same as one-element tools list).
class ToolSelection(BaseModel):
    """Legacy single-tool shape; prefer MultiToolSelection. Parsing accepts this JSON and normalizes."""

    tool_name: str = Field(description="Exact tool name from the provided catalog")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments matching that tool's parameter schema",
    )
    intent: str = Field(
        description="Short natural-language summary of what the user wants"
    )
