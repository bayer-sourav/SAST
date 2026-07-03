"""SQS worker: process queued GitHub advisory jobs."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_SAST = Path(__file__).resolve().parents[2]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from integrations.github.github_auth import installation_token  # noqa: E402
from integrations.github.pipeline import process_workflow_run_event  # noqa: E402
from services.triage_api.job_store import JobStore  # noqa: E402


def _store() -> JobStore:
    return JobStore()


def process_message(body: dict) -> dict:
    store = _store()
    job_id = body.get("job_id")
    event = (body.get("event") or body).get("event") or body.get("event")
    if not isinstance(event, dict):
        raise ValueError("missing workflow_run event")
    installation_id = (event.get("installation") or {}).get("id")
    if not installation_id:
        raise ValueError("missing installation id")
    if job_id:
        store.update(job_id, status="running")
    token = installation_token(installation_id)
    work_root = Path(os.environ.get("TRIAGE_WORK_DIR", tempfile.gettempdir())) / "sast-advisory"
    result = process_workflow_run_event(
        event,
        installation_token=token,
        work_root=work_root,
        sast_root=_SAST,
        publish=True,
    )
    if job_id:
        store.update(job_id, status="completed", result=result)
    return result


def poll_forever() -> None:
    queue_url = os.environ["TRIAGE_QUEUE_URL"]
    import boto3

    sqs = boto3.client("sqs")
    while True:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=900,
        )
        for msg in resp.get("Messages") or []:
            receipt = msg["ReceiptHandle"]
            try:
                body = json.loads(msg["Body"])
                process_message(body)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
            except Exception as exc:  # noqa: BLE001
                print(f"worker error: {exc}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    poll_forever()
