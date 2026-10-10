import hashlib
import os
from datetime import datetime
import requests
from .notifications import notify_user, save_notification
from ..utils.firebase import db
from ..utils.timezone import PH_TZ

REPO = "darinjan13/WIsEnergy-IOT"
VARIANT = "20A"
FILES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "files")
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _headers():
    token = os.getenv("GITHUB_FIRMWARE_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_github_latest():
    r = requests.get(GITHUB_API, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    assets = [a for a in data.get("assets", []) if a["name"].endswith(".bin")]
    if not assets:
        return None
    return {
        "version": data["tag_name"].lstrip("v"),
        "notes": data.get("body", "")[:500],
        "asset_url": assets[0]["url"],
        "asset_name": assets[0]["name"],
    }


def compare_versions(a: str, b: str) -> int:
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    return (pa > pb) - (pa < pb)


def local_bin_path(version: str) -> str:
    os.makedirs(FILES_DIR, exist_ok=True)
    return os.path.join(FILES_DIR, f"wisenergy-20a-{version}.bin")


def mirror_firmware_job():
    try:
        latest = get_github_latest()
    except Exception as e:
        print(f"Firmware mirror: GitHub check failed: {e}")
        return
    if not latest:
        print("Firmware mirror: no .bin asset on latest release.")
        return
    cur = db.reference("/firmware/20A/latest").get() or {}
    if cur.get("version") == latest["version"]:
        return
    path = local_bin_path(latest["version"])
    if not os.path.exists(path):
        dl = requests.get(
            latest["asset_url"],
            headers={**_headers(), "Accept": "application/octet-stream"},
            timeout=120,
        )
        dl.raise_for_status()
        with open(path, "wb") as f:
            f.write(dl.content)
    with open(path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    db.reference("/firmware/20A/latest").set({
        "version": latest["version"],
        "notes": latest["notes"],
        "md5": md5,
        "size": os.path.getsize(path),
        "released_at": datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    })
    print(f"Firmware mirror: published {latest['version']}")
    devices = db.reference("/devices").get() or {}
    for dev_id, dev in devices.items():
        running = ((dev or {}).get("fw") or {}).get("running", "0.0.0")
        owner = (dev or {}).get("owner")
        if owner and compare_versions(running, latest["version"]) < 0:
            notify_user(uid=owner, title="Firmware update available",
                        body=f"Version {latest['version']} is ready for your device.",
                        data={"screen": "devices", "type": "firmware_update"})
            save_notification(owner, "Firmware update available",
                              f"Version {latest['version']} is ready.",
                              ntype="firmware_update")
