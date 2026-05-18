"""Minimal OpenAI-style ``POST /v1/chat/completions`` for local Qwen (no streaming).

Run from repo root: ``python -m models.qwen.openai_chat_server --profile qwen3_8b_bnb``

Point OpenHands at ``http://127.0.0.1:<port>/v1`` with provider ``openai`` and a dummy API key.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

_GEN_LOCK = threading.Lock()


def _parse_tool_calls(text: str) -> tuple[str | None, list[dict[str, Any]]]:
    """Split Qwen-style ``<tool_call>...</tool_call>`` blocks into OpenAI ``tool_calls``."""
    low = text.lower()
    if "<tool_call>" not in low:
        return (text.strip() or None), []

    out_calls: list[dict[str, Any]] = []
    rest_chunks: list[str] = []
    pos = 0
    while True:
        i = low.find("<tool_call>", pos)
        if i < 0:
            rest_chunks.append(text[pos:])
            break
        rest_chunks.append(text[pos:i])
        j = low.find("</tool_call>", i)
        if j < 0:
            rest_chunks.append(text[i:])
            break
        raw = text[i + len("<tool_call>") : j].strip()
        pos = j + len("</tool_call>")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = obj.get("name", "")
        args = obj.get("arguments", {})
        if isinstance(args, dict):
            arg_str = json.dumps(args, ensure_ascii=False)
        else:
            arg_str = str(args)
        cid = f"call_{uuid.uuid4().hex[:12]}"
        out_calls.append(
            {
                "id": cid,
                "type": "function",
                "function": {"name": str(name), "arguments": arg_str},
            }
        )
    content = "".join(rest_chunks).strip() or None
    return content, out_calls


def _chat_completion(body: dict[str, Any], *, profile: str, use_4bit: bool) -> dict[str, Any]:
    if body.get("stream"):
        raise ValueError("stream=true is not supported")

    messages = body.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    tools = body.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = None

    model_name = body.get("model") or "local-qwen"

    from models.qwen.runner import generate_from_chat_messages

    max_tok = body.get("max_tokens")
    prev = None
    if isinstance(max_tok, int) and max_tok > 0:
        prev = os.environ.get("AGENT_MAX_NEW_TOKENS")
        os.environ["AGENT_MAX_NEW_TOKENS"] = str(min(max_tok, 8192))

    try:
        with _GEN_LOCK:
            text = generate_from_chat_messages(
                messages,
                profile=profile,
                use_4bit=use_4bit,
                tools=tools,
            )
    finally:
        if prev is not None:
            os.environ["AGENT_MAX_NEW_TOKENS"] = prev
        elif isinstance(max_tok, int) and max_tok > 0:
            os.environ.pop("AGENT_MAX_NEW_TOKENS", None)

    content, tool_calls = _parse_tool_calls(text)
    if tools and not tool_calls and text:
        content = text.strip() or None

    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class _Handler(BaseHTTPRequestHandler):
    profile: str = "qwen3_8b_bnb"
    use_4bit: bool = True

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"[openai_chat_server] {self.address_string()} - {format % args}")

    def _send_json(self, code: int, obj: dict[str, Any]) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/v1/models", "/v1/models/"):
            payload = {
                "object": "list",
                "data": [{"id": "local-qwen", "object": "model", "created": 0, "owned_by": "local"}],
            }
            self._send_json(200, payload)
            return
        self._send_json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/chat/completions", "/v1/chat/completions/"):
            self._send_json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send_json(
                400,
                {"error": {"message": f"invalid json: {exc}", "type": "invalid_request_error"}},
            )
            return

        try:
            out = _chat_completion(body, profile=self.profile, use_4bit=self.use_4bit)
        except ValueError as exc:
            self._send_json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return
        except Exception as exc:  # pragma: no cover
            self._send_json(
                500,
                {"error": {"message": str(exc), "type": "internal_error"}},
            )
            return

        self._send_json(200, out)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--profile", default=os.environ.get("QWEN_PROFILE", "qwen3_8b_bnb"))
    ap.add_argument("--no-4bit", action="store_true", help="Load full precision (more VRAM).")
    args = ap.parse_args()

    _Handler.profile = args.profile
    _Handler.use_4bit = not args.no_4bit

    server = HTTPServer((args.host, args.port), _Handler)
    print(
        f"[openai_chat_server] Listening http://{args.host}:{args.port} "
        f"(profile={args.profile!r}, POST /v1/chat/completions)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[openai_chat_server] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
