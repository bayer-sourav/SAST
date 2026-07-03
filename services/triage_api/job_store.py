"""Job store backed by DynamoDB (or in-memory for local dev)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStore:
    def __init__(self, table_name: str | None = None) -> None:
        self.table_name = table_name or os.environ.get("TRIAGE_JOBS_TABLE")
        self._memory: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        item = {
            "job_id": job_id,
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
            "payload": payload,
        }
        if self.table_name:
            import boto3

            boto3.resource("dynamodb").Table(self.table_name).put_item(Item=_dynamo_item(item))
        else:
            self._memory[job_id] = item
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        if self.table_name:
            import boto3

            resp = boto3.resource("dynamodb").Table(self.table_name).get_item(Key={"job_id": job_id})
            item = resp.get("Item")
            return _from_dynamo(item) if item else None
        return self._memory.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        item = self.get(job_id) or {"job_id": job_id}
        item.update(fields)
        item["updated_at"] = _now()
        if self.table_name:
            import boto3

            boto3.resource("dynamodb").Table(self.table_name).put_item(Item=_dynamo_item(item))
        else:
            self._memory[job_id] = item


def _dynamo_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    if "payload" in out and not isinstance(out["payload"], str):
        out["payload"] = json.dumps(out["payload"])
    if "result" in out and not isinstance(out["result"], str):
        out["result"] = json.dumps(out["result"])
    return out


def _from_dynamo(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for key in ("payload", "result"):
        if key in out and isinstance(out[key], str):
            out[key] = json.loads(out[key])
    return out
