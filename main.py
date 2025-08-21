import threading
from fastapi import FastAPI, Request, Response
from firebase_admin import credentials, db, initialize_app
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from pytz import timezone
import random

app = FastAPI()

PH_TZ = timezone("Asia/Manila")

cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(
    cred,
    {
        "databaseURL": "https://capstone-238eb-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)


def summary_aggregation():
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")
    target_date = (now_ph - timedelta(days=1)).strftime("%Y-%m-%d")
    month_key = now_ph.strftime("%Y-%m")
    interval_seconds = 5

    is_monday = now_ph.weekday() == 0
    is_first_of_month = now_ph.day == 1

    def get_week_label(date):
        start_of_week = date - timedelta(days=date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        week_number = int(start_of_week.strftime("%U"))
        return f"Week {week_number} ({start_of_week.strftime('%b %d')}–{end_of_week.strftime('%d')})"

    print("📊 Starting summary aggregation...")

    usage_root = db.reference("/usage").get()
    if not usage_root:
        print("⚠️ No usage data.")
        return

    for user_id, devices in usage_root.items():
        for device_id, appliances in devices.items():
            for appliance_name, dates in appliances.items():
                # -- DAILY --
                day_data = dates.get(target_date)
                if not day_data:
                    continue

                powers = [record.get("power", 0) for record in day_data.values()]
                if not powers:
                    continue

                total_kwh = sum((p / 1000) * (interval_seconds / 3600) for p in powers)
                avg_power = sum(powers) / len(powers)
                max_power = max(powers)

                db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
                ).set(
                    {
                        "total_kWh": round(total_kwh, 6),
                        "avg_power": round(avg_power, 2),
                        "max_power": round(max_power, 2),
                        "updated_at": now_str,
                    }
                )

                # -- WEEKLY --
                if is_monday:
                    last_7_days = [
                        (now_ph - timedelta(days=i)).strftime("%Y-%m-%d")
                        for i in range(7)
                    ]
                    total_kwh_week = 0
                    for d in last_7_days:
                        summary = db.reference(
                            f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{d}"
                        ).get()
                        if summary:
                            total_kwh_week += summary.get("total_kWh", 0)

                    week_label = get_week_label(now_ph)
                    db.reference(
                        f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{week_label}"
                    ).set(
                        {"total_kWh": round(total_kwh_week, 6), "updated_at": now_str}
                    )

                # -- MONTHLY --
                if is_first_of_month:
                    total_kwh_month = 0
                    for d, summary in dates.items():
                        if d.startswith(month_key):
                            total_kwh_month += summary.get("total_kWh", 0)

                    db.reference(
                        f"/monthly_summary/{user_id}/{device_id}/{appliance_name}/{month_key}"
                    ).set(
                        {"total_kWh": round(total_kwh_month, 6), "updated_at": now_str}
                    )

    print(
        "✅ Aggregation completed (Daily"
        + (", Weekly" if is_monday else "")
        + (", Monthly" if is_first_of_month else "")
        + ")"
    )


def total_energy_consumption():
    now_ph = datetime.now(PH_TZ)
    today_str = now_ph.strftime("%Y-%m-%d")
    month_key = now_ph.strftime("%Y-%m")

    is_monday = now_ph.weekday() == 0
    is_first_of_month = now_ph.day == 1

    def get_week_label(date):
        start_of_week = date - timedelta(days=date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        week_number = int(start_of_week.strftime("%U"))
        return f"Week {week_number} ({start_of_week.strftime('%b %d')}–{end_of_week.strftime('%d')})"

    print("📊 Calculating total energy consumption...")

    # -- DAILY TOTAL --
    daily_root = db.reference("/daily_summary").get()
    if daily_root:
        for user_id, devices in daily_root.items():
            total_kwh_daily = sum(
                summary.get("total_kWh", 0)
                for device in devices.values()
                for appliance in device.values()
                for date, summary in appliance.items()
                if date == today_str
            )
            db.reference(f"/daily_total_consumption/{user_id}/{today_str}").set(
                {"total_energy_consumption": round(total_kwh_daily, 2)}
            )

    # -- WEEKLY TOTAL --
    if is_monday:
        week_label = get_week_label(now_ph)
        weekly_root = db.reference("/weekly_summary").get()
        if weekly_root:
            for user_id, devices in weekly_root.items():
                total_kwh_weekly = sum(
                    summary.get("total_kWh", 0)
                    for device in devices.values()
                    for appliance in device.values()
                    for week, summary in appliance.items()
                    if week == week_label
                )
                db.reference(f"/weekly_total_consumption/{user_id}/{week_label}").set(
                    {"total_energy_consumption": round(total_kwh_weekly, 2)}
                )

    # -- MONTHLY TOTAL --
    if is_first_of_month:
        monthly_root = db.reference("/monthly_summary").get()
        if monthly_root:
            for user_id, devices in monthly_root.items():
                total_kwh_monthly = sum(
                    summary.get("total_kWh", 0)
                    for device in devices.values()
                    for appliance in device.values()
                    for month, summary in appliance.items()
                    if month == month_key
                )
                db.reference(f"/monthly_total_consumption/{user_id}/{month_key}").set(
                    {"total_energy_consumption": round(total_kwh_monthly, 2)}
                )

    print(
        "✅ Total energy consumption updated (Daily"
        + (", Weekly" if is_monday else "")
        + (", Monthly" if is_first_of_month else "")
        + ")"
    )


scheduler = BackgroundScheduler()
scheduler.add_job(summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ)
scheduler.start()


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
