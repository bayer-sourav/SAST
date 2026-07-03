"""GitHub App webhook receiver → enqueue or process advisory jobs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from integrations.github.github_auth import installation_token  # noqa: E402
from integrations.github.github_client import verify_webhook_signature  # noqa: E402
from integrations.github.pipeline import process_workflow_run_event  # noqa: E402

app = FastAPI(title="SAST GitHub Advisory Webhook", version="1.0.0")


def _verify_hmac(body: bytes, signature: str | None) -> None:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET") or os.environ.get("TRIAGE_API_HMAC_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="webhook secret not configured")
    if not verify_webhook_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")


def _enqueue_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Send job to triage API queue (SQS) when TRIAGE_QUEUE_URL is set."""
    queue_url = os.environ.get("TRIAGE_QUEUE_URL")
    if not queue_url:
        return {"queued": False}
    import boto3

    sqs = boto3.client("sqs")
    body = json.dumps(payload)
    resp = sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    return {"queued": True, "message_id": resp.get("MessageId")}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> JSONResponse:
    body = await request.body()
    _verify_hmac(body, x_hub_signature_256)
    event = json.loads(body.decode("utf-8"))

    if x_github_event != "workflow_run":
        return JSONResponse({"status": "ignored", "event": x_github_event})

    action = event.get("action")
    if action != "completed":
        return JSONResponse({"status": "ignored", "action": action})

    queued = _enqueue_job(
        {
            "type": "workflow_run",
            "delivery_id": x_github_delivery,
            "event": event,
        }
    )
    if queued.get("queued"):
        return JSONResponse({"status": "queued", **queued})

    # Inline processing (dev / single-node deploy)
    installation_id = (event.get("installation") or {}).get("id")
    if not installation_id:
        raise HTTPException(status_code=400, detail="missing installation id")
    token = installation_token(installation_id)
    work_root = Path(os.environ.get("TRIAGE_WORK_DIR", tempfile.gettempdir())) / "sast-advisory"
    result = process_workflow_run_event(
        event,
        installation_token=token,
        work_root=work_root,
        sast_root=_SAST,
        publish=True,
    )
    return JSONResponse({"status": "completed", "summary": result.get("summary"), "n_cases": result.get("n_cases")})


def main() -> None:
    import uvicorn

    uvicorn.run(
        "integrations.github.app.webhook_server:app",
        host=os.environ.get("WEBHOOK_HOST", "0.0.0.0"),
        port=int(os.environ.get("WEBHOOK_PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
