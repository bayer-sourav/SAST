"""LangChain-oriented prompts and structured JSON instructions for tool selection."""

from __future__ import annotations

import json
from typing import Any, cast

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool

from core.schemas import MultiToolSelection

_DESC_MAX = 140
_PARAM_KEYS_MAX = 16


def _one_line(s: str | None, *, max_len: int = _DESC_MAX) -> str:
    if not s:
        return ""
    t = " ".join(str(s).split())
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _param_names_compact(params: dict[str, Any]) -> str:
    """Short list of parameter names (and rough types from JSON Schema if present)."""
    if not params:
        return "(none)"
    props = params.get("properties")
    if isinstance(props, dict) and props:
        parts: list[str] = []
        for name in list(props.keys())[:_PARAM_KEYS_MAX]:
            spec = props.get(name) or {}
            t = spec.get("type")
            if isinstance(t, list) and t:
                t = t[0]
            parts.append(f"{name}" + (f":{t}" if t else ""))
        tail = " …" if len(props) > _PARAM_KEYS_MAX else ""
        return ", ".join(parts) + tail
    keys = [str(k) for k in params.keys() if k != "properties"][:_PARAM_KEYS_MAX]
    if not keys and isinstance(params, dict):
        keys = [str(k) for k in params.keys()][: _PARAM_KEYS_MAX]
    tail = " …" if len(params) > _PARAM_KEYS_MAX else ""
    return ", ".join(keys) + tail if keys else "(object)"


def _tool_params_dict(t: BaseTool) -> dict[str, Any]:
    args = getattr(t, "args", None)
    schema_obj: Any = getattr(t, "args_schema", None)
    if args:
        return dict(args)
    if schema_obj is not None:
        mjs = getattr(schema_obj, "model_json_schema", None)
        if callable(mjs):
            return cast(dict[str, Any], mjs())
        if isinstance(schema_obj, dict):
            return dict(schema_obj)
    return {}


def tool_catalog_compact_lines(tools: list[BaseTool]) -> str:
    """One line per tool: name, short description, minimal parameter hint (not full JSON Schema)."""
    lines: list[str] = []
    for t in tools:
        params = _tool_params_dict(t)
        hint = _param_names_compact(params)
        desc = _one_line(getattr(t, "description", None) or "")
        lines.append(f"- {t.name}: {desc}  [params: {hint}]")
    return "\n".join(lines)


def tool_catalog_block(tools: list[BaseTool]) -> str:
    """Verbose JSON catalog (kept for tests or callers that need full schema dump)."""
    entries: list[dict[str, Any]] = []
    for t in tools:
        params = _tool_params_dict(t)
        entries.append(
            {
                "name": t.name,
                "description": t.description,
                "parameters": params,
            }
        )
    return json.dumps(entries, indent=2)


_OUTPUT_SCHEMA_HINT = """Required JSON object (one only, no markdown fences if possible):
- "tools": [ { "tool_name": "<exact catalog name>", "parameters": { ... } }, ... ]
- "intent": string, one sentence summarizing the user's goal
- "reasoning": string, brief narrative of why you chose these tools and this order (single-turn ReAct-style)
- "steps": array of short strings, each one discrete reasoning step (Thought-like), in order; use [] if none
Each "parameters" object uses only keys valid for that tool and JSON types (string, number, boolean, object, array)."""


def tool_selection_system_prompt(tools: list[BaseTool]) -> str:
    catalog = tool_catalog_compact_lines(tools)
    return f"""You are a multi-tool routing agent. Select the **smallest** set of catalog tools that fully
satisfies the user message—no extras. One tool when one action suffices; two or more only when the user
clearly asks for distinct actions. Order tools by sensible dependencies.

Output (strict):
- Respond with ONLY one JSON object (raw JSON). First character "{{", last "}}".
- If you must use markdown, put the JSON inside a ```json code fence``` — fenced JSON is accepted.
- No preamble/epilogue prose outside JSON. No Python/OpenAI tool-call syntax.

{_OUTPUT_SCHEMA_HINT}

Example (names/args must match the real catalog below):
{{"tools": [{{"tool_name": "get_weather", "parameters": {{"location": "Paris", "units": "celsius"}}}}], "intent": "Check weather in Paris.", "reasoning": "User asked for Paris conditions; get_weather is the only catalog tool needed.", "steps": ["Parse location as Paris.", "Select get_weather with metric units."]}}

Rules:
- tool_name must match a catalog name exactly. parameters only use keys allowed for that tool.
- Always include "reasoning" and "steps" (steps may be [] if a single reasoning string suffices).
- Keep string parameters short (e.g. email body ~2 sentences) to avoid truncated JSON.

Tool catalog (compact):
{catalog}
"""


def build_tool_selection_prompt_template() -> ChatPromptTemplate:
    """LangChain chat template: system (tool catalog) + human (user task)."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            ("human", "User message:\n{user_message}"),
        ]
    )


def build_tool_selection_chain_inputs(
    tools: list[BaseTool], user_message: str
) -> dict[str, str]:
    """Inputs for LCEL-style binding: prompt | llm | parser (llm supplied per backend)."""
    return {
        "system_prompt": tool_selection_system_prompt(tools),
        "user_message": user_message,
    }


def get_tool_selection_json_parser() -> JsonOutputParser:
    return JsonOutputParser(pydantic_object=MultiToolSelection)


def tool_selection_chat_messages(
    tools: list[BaseTool], user_message: str
) -> list[dict[str, str]]:
    """OpenAI-style role/content messages for HF chat templates."""
    template = build_tool_selection_prompt_template()
    lc_messages = template.format_messages(
        **build_tool_selection_chain_inputs(tools, user_message)
    )
    out: list[dict[str, str]] = []
    for m in lc_messages:
        role = "system" if m.type == "system" else "user"
        content = m.content
        text = content if isinstance(content, str) else str(content)
        out.append({"role": role, "content": text})
    return out


def fold_system_into_user_for_gemma2(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Gemma 2 instruct chat templates reject role \"system\" (TemplateError: System role not supported).
    Merge [system, user, ...] into a single user turn for apply_chat_template.
    """
    if not messages:
        return messages
    if len(messages) == 1 and messages[0].get("role") == "system":
        return [{"role": "user", "content": messages[0]["content"]}]
    if (
        len(messages) >= 2
        and messages[0].get("role") == "system"
        and messages[1].get("role") == "user"
    ):
        sys_t = messages[0]["content"]
        usr_t = messages[1]["content"]
        merged = f"{sys_t}\n\n{usr_t}"
        return [{"role": "user", "content": merged}, *messages[2:]]
    return list(messages)
