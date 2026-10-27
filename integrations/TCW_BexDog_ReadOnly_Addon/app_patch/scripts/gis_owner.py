"""Host-only BexDog veto. Uses local owner credentials, never browser credentials alone."""
import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError, HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.owner_credentials import owner_token_path
from backend.gis_bridge import GisBridge


def main():
    parser = argparse.ArgumentParser(description="Host controls for the read-only BexDog connection")
    parser.add_argument("action", choices=["status", "cancel", "pause", "resume"], default="status", nargs="?")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config/settings.example.json").read_text(encoding="utf-8-sig"))
    custom = root / "config/settings.json"
    if custom.exists():
        cfg.update(json.loads(custom.read_text(encoding="utf-8-sig")))
    port = int(cfg.get("port", 8765))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid local application port.")
    base = "http://127.0.0.1:" + str(port)
    opener = build_opener(ProxyHandler({}))
    direct_cancel = False
    # Independent SDK veto path: it remains usable if the web server is stuck.
    # Pause persists, and the service checks the marker before every new question.
    if args.action in {"cancel", "pause"}:
        private_path = owner_token_path(root)
        if private_path.exists():
            private_path.with_suffix(".paused").write_text("Host paused GIS requests.\n", encoding="utf-8")
            bridge = GisBridge()
            active_sdk_job = bridge.status().get("job_id")
            if active_sdk_job:
                bridge.cancel(active_sdk_job)
                direct_cancel = True
    try:
        owner = owner_token_path(root).read_text(encoding="utf-8").strip()
        session = (root / "logs/session-token").read_text(encoding="utf-8").strip()
        headers = {"X-TCW-Owner": owner, "X-TCW-Token": session, "Content-Type": "application/json"}
        def request(path, payload=None):
            req = Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
            with opener.open(req, timeout=10) as response:
                return json.load(response)
        state = request("/api/gis/admin/status")
        if args.action != "status":
            active = state.get("active") or {}
            current = active.get("id") or state["bridge"].get("job_id")
            payload = {"action": args.action}
            if args.action == "cancel" and current:
                payload["request_id"] = current
            state = request("/api/gis/admin/control", payload)
        print(json.dumps(state, indent=2))
        if args.action in {"cancel", "pause"}:
            print("Host veto applied. New GIS requests are paused. Run Resume_BexDog.cmd when ready.")
            print("If cancellation_pending is true or the SDK is busy, ArcGIS is still finishing a read.")
        return 0
    except (OSError, URLError, ValueError) as exc:
        if direct_cancel:
            print("A cancellation request was delivered directly to the SDK. The web server did not acknowledge owner control.")
            print("The pause marker is saved. ArcGIS may still be finishing a read; inspect the BexDog pane.")
        print("Owner control failed: " + (str(exc.code) if isinstance(exc, HTTPError) else type(exc).__name__))
        print("Start the TCW assistant on this workstation, then retry. The ArcGIS BexDog pane also has Cancel.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
