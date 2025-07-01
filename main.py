import threading
from fastapi import FastAPI, Request, Response
from firebase_admin import credentials, db, initialize_app
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from pytz import timezone

app = FastAPI()

PH_TZ = timezone("Asia/Manila")

cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(
    cred,
    {
        "databaseURL": "https://capstone-238eb-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)


def daily_total_energy_consumption():
    now_ph = datetime.now(PH_TZ)
    target_date = now_ph.strftime("%Y-%m-%d")

    daily_root = db.reference(f"/daily_summary")
    daily_data = daily_root.get()
    if not daily_data:
        print("⚠️ No daily summary data.")
        return

    for user_id, devices in daily_data.items():
        total_kwh = 0
        for device_id, appliances in devices.items():
            for appliance_name, dates in appliances.items():
                for date, summary in dates.items():
                    if date == target_date:
                        total_kwh += summary.get("total_kWh", 0)

        daily_total_consumption_ref = db.reference(
            f"/daily_total_consumption/{user_id}/{target_date}/total_energy_consumption"
        )
        daily_total_consumption_ref.set(round(total_kwh, 2))

        user_total_ref = db.reference(f"/users/{user_id}/total_energy_consumption")
        prev_total = user_total_ref.get() or 0
        new_total = round(prev_total + total_kwh, 2)
        user_total_ref.set(new_total)
        print(f"✅ Total energy for {user_id} on {target_date}: {total_kwh:.2f} kWh")


def daily_summary_aggregation():
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")
    print("📊 Starting daily summary aggregation...")

    usage_root = db.reference("/usage")
    usage_data = usage_root.get()
    if not usage_data:
        print("⚠️ No usage data.")
        return

    target_date = (now_ph - timedelta(days=1)).strftime("%Y-%m-%d")
    interval_seconds = 5

    for user_id, devices in usage_data.items():
        for device_id, appliances in devices.items():
            for appliance_name, dates in appliances.items():
                day_data = dates.get(target_date)
                if not day_data:
                    continue

                powers = [record.get("power", 0) for record in day_data.values()]
                if not powers:
                    continue

                total_kwh = sum((p / 1000) * (interval_seconds / 3600) for p in powers)
                if total_kwh == 0:
                    print(
                        f"⏩ Skipped summary for {user_id} | {device_id} | {appliance_name} — 0 kWh"
                    )
                    continue

                avg_power = sum(powers) / len(powers)
                max_power = max(powers)

                summary_ref = db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
                )
                summary_ref.set(
                    {
                        "total_kWh": round(total_kwh, 6),
                        "avg_power": round(avg_power, 2),
                        "max_power": round(max_power, 2),
                        "updated_at": now_str,
                    }
                )

                print(
                    f"✅ Summary saved for {user_id} | {device_id} | {appliance_name} | {target_date}"
                )


def update_latest_kwh(user_id, device_id, appliance_name, date, interval_seconds=3):
    usage_day_ref = db.reference(
        f"/usage/{user_id}/{device_id}/{appliance_name}/{date}"
    )
    day_data = usage_day_ref.get() or {}
    print(usage_day_ref.path)

    powers = [
        entry.get("power", 0)
        for key, entry in day_data.items()
        if isinstance(entry, dict)
    ]
    total_kwh = sum((p / 1000) * (interval_seconds / 3600) for p in powers)

    appliance_ref = db.reference(
        f"/appliances/{user_id}/{device_id}/{appliance_name}/latest_kwh"
    )
    print(total_kwh)
    appliance_ref.set(round(total_kwh, 2))


def listen_for_active_appliances():
    print("Listener function started")
    ref = db.reference("/appliances")

    def listener(event):
        if isinstance(event.data, dict):
            for key, value in event.data.items():
                if key.endswith("/is_active") and value == True:
                    path = event.path + "/" + key
                    parts = path.strip("/").split("/")
                    if len(parts) >= 4:
                        print("ASD", key)
                        user_id, device_id, appliance_name, _ = parts
                        now_ph = datetime.now(PH_TZ)
                        today = now_ph.strftime("%Y-%m-%d")
                        print(
                            f"🔔 Detected active appliance: {user_id} | {device_id} | {appliance_name} | {today}"
                        )
                        update_latest_kwh(user_id, device_id, appliance_name, today)

    ref.listen(listener)


def start_listener():
    threading.Thread(target=listen_for_active_appliances, daemon=True).start()


scheduler = BackgroundScheduler()
scheduler.add_job(daily_summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(
    daily_total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ
)
scheduler.start()

start_listener()


@app.get("/")
def root():
    return {"message": "WisEnergy daily summary updater is active."}


@app.api_route("/ping", methods=["GET", "HEAD"])
def ping(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return {"message": "pong"}


@app.get("/status")
def status():
    return {
        "status": "running",
        "server_time": datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "scheduler": "active",
    }
