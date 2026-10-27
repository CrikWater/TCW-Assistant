"""Per-user local transport to the read-only ArcGIS SDK gateway.

Only the host application calls this module; the web API never accepts tool names.
No TCP listener, shell, executable code, SQL or GIS file writes are implemented.
"""
import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from backend.config import AppError

PROTOCOL = "tcw-gis-readonly-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def read_json(path, limit):
    with path.open("rb") as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Bridge file exceeds its size limit.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Bridge file must be an object.")
    return value


class GisBridge:
    def __init__(self, directory=None, timeout=120, poll=0.2):
        local = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
        self.directory = Path(directory) if directory else (
            Path(local) / "TCW" / "BexDogReadOnlyBridge" if local else None)
        self.timeout = min(max(timeout, 0.05), 120)
        self.poll = poll

    def status(self):
        offline = {"available": False, "read_only": True, "protocol": PROTOCOL,
                   "message": "Open ArcGIS Pro and the patched BexDog pane under the same Windows account as this assistant."}
        if self.directory is None:
            return {**offline, "message": "The BexDog SDK bridge requires the Windows GIS workstation."}
        try:
            d = read_json(self.directory / "provider.json", 8192)
            age = time.time() * 1000 - d["heartbeat_ms"]
            if (d.get("protocol") != PROTOCOL or d.get("read_only") is not True
                    or not isinstance(d.get("session_id"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", d["session_id"])
                    or not -5000 <= age <= 15000):
                return offline
            return {"available": True, "read_only": True, "protocol": PROTOCOL,
                    "session_id": d["session_id"], "busy": bool(d.get("busy")),
                    "job_id": d.get("job_id"), "cancellation_pending": bool(d.get("cancellation_pending")),
                    "bexdog_version": d.get("bexdog_version"),
                    "message": "BexDog read-only bridge is responding. Each query checks the map."}
        except (OSError, ValueError, KeyError, TypeError):
            return offline

    def cancel(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
            raise ValueError("Invalid cancellation request ID.")
        if self.directory is not None and self.directory.is_dir():
            # Non-executable marker. Kept ten minutes to reject delayed requests.
            (self.directory / (job_id + ".cancel")).write_text("host cancelled\n", encoding="utf-8")

    async def call(self, operation, payload, job_id, session, expected_map_uri=None):
        if operation not in {"catalog", "tool"} or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise AppError("Unsupported GIS transport operation.", 400, "gis_invalid_request")
        status = self.status()
        if not status["available"]:
            raise AppError(status["message"], 503, "gis_offline")
        if status["session_id"] != session:
            raise AppError("The ArcGIS session changed. Start a new question.", 409, "gis_session_changed")
        if status["busy"]:
            raise AppError("BexDog is still processing a request. Wait for its SDK read to finish.", 409, "gis_busy")
        request_id = uuid.uuid4().hex
        started_ms = int(time.time() * 1000)
        deadline_ms = started_ms + int(self.timeout * 1000)
        request = {"protocol": PROTOCOL, "id": request_id, "job_id": job_id, "session_id": session,
                   "created_ms": started_ms, "deadline_ms": deadline_ms,
                   "operation": operation, "payload": payload}
        if expected_map_uri is not None:
            request["expected_map_uri"] = expected_map_uri
        destination = self.directory / (request_id + ".request.json")
        temporary = self.directory / (request_id + ".request.tmp")
        response = self.directory / (request_id + ".response.json")
        started = time.monotonic()
        try:
            if (self.directory / (job_id + ".cancel")).exists():
                raise AppError("The host cancelled this request.", 409, "gis_cancelled")
            raw = json.dumps(request, ensure_ascii=False)
            if len(raw.encode("utf-8")) > 16384:
                raise ValueError("GIS request too large.")
            with temporary.open("x", encoding="utf-8") as f:
                f.write(raw)
            os.replace(temporary, destination)
            while time.monotonic() - started < self.timeout:
                if response.exists():
                    d = read_json(response, MAX_RESPONSE_BYTES)
                    if (d.get("protocol") != PROTOCOL or d.get("id") != request_id
                            or d.get("job_id") != job_id or d.get("session_id") != session
                            or d.get("read_only") is not True
                            or not started_ms <= d.get("completed_ms", 0) <= deadline_ms
                            or not isinstance(d.get("reply"), dict)):
                        raise ValueError("Uncorrelated or invalid GIS response.")
                    reply = d["reply"]
                    if reply.get("status") == "cancelled":
                        raise AppError("The host cancelled this request or its time limit expired.", 409, "gis_cancelled")
                    if reply.get("status") == "error":
                        raise AppError(str(reply.get("error", "The SDK read failed."))[:1000], 502, "gis_sdk_error")
                    if reply.get("status") != "ok" or "data" not in reply:
                        raise ValueError("Invalid SDK result.")
                    return {**reply, "completed_ms": d["completed_ms"], "elapsed_s": time.monotonic() - started}
                current = self.status()
                if not current["available"] or current.get("session_id") != session:
                    raise AppError("The BexDog session stopped responding. Start a new question after reopening the pane.", 503, "gis_disconnected")
                await asyncio.sleep(self.poll)
            self.cancel(job_id)
            raise AppError("GIS read timed out; cancellation requested. An in-progress ArcGIS read may need time to finish.", 504, "gis_timeout")
        except asyncio.CancelledError:
            self.cancel(job_id)
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise AppError("The GIS response could not be verified. No result was displayed.", 502, "gis_invalid_response") from exc
        finally:
            for p in (temporary, destination, response):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
