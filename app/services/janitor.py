from datetime import datetime
from ..utils.firebase import db
from ..utils.timezone import PH_TZ


def janitor_delete_processed_hours():
    """Delete raw per-second nodes whose hour is already in daily_summary.

    Keeps today fully (live debugging) and every unsummarized hour forever
    (visible leftovers, never silent loss). Storage plateaus at ~2 days.
    """
    today = datetime.now(PH_TZ).strftime("%Y-%m-%d")
    users = db.reference("/usage").get(shallow=True) or {}
    deleted_hours = 0
    for user_id in users:
        devices = db.reference(f"/usage/{user_id}").get(shallow=True) or {}
        for device_id in devices:
            appliances = (
                db.reference(f"/usage/{user_id}/{device_id}").get(shallow=True) or {}
            )
            for appliance in appliances:
                dates = (
                    db.reference(f"/usage/{user_id}/{device_id}/{appliance}").get(shallow=True)
                    or {}
                )
                for date in dates:
                    if date >= today:
                        continue
                    summary = (
                        db.reference(
                            f"/daily_summary/{user_id}/{device_id}/{appliance}/{date}/hourly"
                        ).get()
                        or {}
                    )
                    day_ref = db.reference(
                        f"/usage/{user_id}/{device_id}/{appliance}/{date}"
                    )
                    stamps = day_ref.get(shallow=True) or {}
                    for ts in stamps:
                        hour_key = ts[:2] + ":00" if len(ts) >= 2 and ts[:2].isdigit() else None
                        if hour_key and hour_key in summary:
                            day_ref.child(ts).delete()
                            deleted_hours += 1
    print(f"Janitor: deleted {deleted_hours} processed hour-nodes (kept {today} intact).")
