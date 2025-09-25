import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta
from pytz import timezone

# Initialize Firebase (use your service account key JSON)
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": "https://wisenergy-11737-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)


def backfill_single_day_usage(
    input_file, target_date, user_id, device_id, appliance_name
):
    """
    Process a usage.json (time-only -> power) for a single day
    and push a daily_summary entry to Firebase.
    """

    with open(input_file, "r") as f:
        usage_data = json.load(f)

    readings = []
    for time_str, record in usage_data.items():
        if "power" not in record:
            continue
        try:
            t = datetime.strptime(f"{target_date} {time_str}", "%Y-%m-%d %H_%M_%S")
            readings.append((t, float(record["power"])))
        except Exception:
            continue

    if len(readings) < 2:
        print(f"❌ Not enough readings for {target_date}")
        return None

    readings.sort(key=lambda x: x[0])
    powers = [p for _, p in readings]
    max_power = max(powers)

    total_kWh = 0.0
    hourly = {}

    for i in range(len(readings) - 1):
        t1, p1 = readings[i]
        t2, _ = readings[i + 1]

        interval_sec = (t2 - t1).total_seconds()
        if interval_sec <= 0:
            continue

        interval_hr = interval_sec / 3600
        kWh = (p1 * interval_hr) / 1000
        total_kWh += kWh

        hour_key = t1.strftime("%H:00")
        hourly[hour_key] = hourly.get(hour_key, 0) + kWh

    # Time-weighted daily average power
    total_hours = (readings[-1][0] - readings[0][0]).total_seconds() / 3600
    avg_power = (
        (total_kWh * 1000) / total_hours
        if total_hours > 0
        else sum(powers) / len(powers)
    )

    updated_at = readings[-1][0].strftime("%Y-%m-%d %H:%M:%S")

    summary = {
        "avg_power": round(avg_power, 2),
        "hourly": {h: round(v, 6) for h, v in hourly.items()},
        "max_power": round(max_power, 2),
        "total_kWh": round(total_kWh, 5),
        "updated_at": updated_at,
    }

    # Push to Firebase
    ref = db.reference(
        f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
    )
    ref.set(summary)

    print(f"✅ Backfilled {target_date} for {appliance_name} → {summary}")
    return summary


def backfill_multi_day_usage(input_file, user_id, device_id, appliance_name):
    """
    Process a usage.json with multiple days of data (date -> times -> power)
    and push daily_summary for each day to Firebase.
    """

    with open(input_file, "r") as f:
        usage_data = json.load(f)

    for target_date, times in usage_data.items():
        readings = []
        for time_str, record in times.items():
            if "power" not in record:
                continue
            t = datetime.strptime(f"{target_date} {time_str}", "%Y-%m-%d %H_%M_%S")
            readings.append((t, record["power"]))

        if not readings:
            print(f"⚠️ Skipped {target_date} (no valid readings)")
            continue

        readings.sort(key=lambda x: x[0])
        powers = [p for _, p in readings]
        avg_power = sum(powers) / len(powers)
        max_power = max(powers)

        total_kWh = 0.0
        hourly = {}

        for i in range(len(readings) - 1):
            t1, p1 = readings[i]
            t2, _ = readings[i + 1]

            interval_sec = (t2 - t1).total_seconds()
            interval_hr = interval_sec / 3600

            kWh = (p1 * interval_hr) / 1000
            total_kWh += kWh

            hour_key = t1.strftime("%H:00")
            hourly[hour_key] = hourly.get(hour_key, 0) + kWh

        updated_at = readings[-1][0].strftime("%Y-%m-%d %H:%M:%S")

        summary = {
            "avg_power": round(avg_power, 2),
            "hourly": {h: round(v, 6) for h, v in hourly.items()},
            "max_power": round(max_power, 2),
            "total_kWh": round(total_kWh, 5),
            "updated_at": updated_at,
        }

        # Push to Firebase
        ref = db.reference(
            f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
        )
        ref.set(summary)

        print(f"✅ Backfilled {target_date} for {appliance_name} → {summary}")

    print("🎉 Backfill complete.")


PH_TZ = timezone("Asia/Manila")


def hourly_summary_update():
    now_ph = datetime.now(PH_TZ)
    today = now_ph.strftime("%Y-%m-%d")
    hour_key = now_ph.strftime("%H:00")
    interval_seconds = 5

    print(f"📊 Running hourly summary update for {today} {hour_key}...")

    users_ref = db.reference("/usage")
    users = users_ref.get(shallow=True)
    if not users:
        print("⚠️ No usage data.")
        return

    for user_id in users:
        devices_ref = db.reference(f"/usage/{user_id}")
        devices = devices_ref.get(shallow=True)

        for device_id in devices or {}:
            appliances_ref = db.reference(f"/usage/{user_id}/{device_id}")
            appliances = appliances_ref.get(shallow=True)

            for appliance_name in appliances or {}:
                # 🚀 only fetch today + current hour
                day_ref = db.reference(
                    f"/usage/{user_id}/{device_id}/{appliance_name}/{today}"
                )
                day_data = day_ref.get()

                if not day_data:
                    continue

                # Only take entries from the current hour
                powers = []
                for ts, rec in (day_data or {}).items():
                    try:
                        ts_dt = datetime.strptime(ts, "%H_%M_%S")
                        if ts_dt.hour == now_ph.hour:
                            powers.append(float(rec.get("power", 0)))
                    except:
                        continue

                if not powers:
                    continue

                total_kwh_hour = sum(
                    (p / 1000.0) * (interval_seconds / 3600.0) for p in powers
                )
                avg_power_hour = sum(powers) / len(powers)
                max_power_hour = max(powers)

                daily_ref = db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{today}"
                )
                existing = daily_ref.get() or {}

                # 🚀 set hourly then recompute total
                hourly_ref = daily_ref.child("hourly")
                hourly_ref.update({hour_key: round(total_kwh_hour, 6)})
                all_hourly = hourly_ref.get() or {}
                new_total = sum(all_hourly.values())

                daily_ref.update(
                    {
                        "total_kWh": round(new_total, 6),
                        "avg_power": round(avg_power_hour, 2),
                        "max_power": max(
                            float(existing.get("max_power", 0)), max_power_hour
                        ),
                        "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                print(f"{user_id}/{device_id}/{appliance_name}/{today}/{hour_key} ✅")

    print("✅ Hourly summary update completed.")


import json
from datetime import datetime, timedelta
from firebase_admin import db


def backfill_weekly_from_export(input_file: str):
    """
    Read an export shaped like:
      { "<uid>": { "<deviceId>": { "<applianceName>": { "YYYY-MM-DD": {...} } } } }
    and write weekly_summary for every device/appliance.

    Weekly bucket path (to match your schema):
      /weekly_summary/{uid}/{deviceId}/{appliance}/{YYYY}/{MM}/{WW}
      where WW = 01..05 (nth Monday-owned week of that month)
    """

    with open(input_file, "r") as f:
        exported = json.load(f)

    for user_id, devices in (exported or {}).items():
        for device_id, appliances in (devices or {}).items():
            for appliance_name, daily_data in (appliances or {}).items():
                print(f"📊 Processing {user_id}/{device_id}/{appliance_name}")

                if not isinstance(daily_data, dict) or not daily_data:
                    continue

                # All dates we have for this appliance
                try:
                    date_objs = sorted(
                        datetime.strptime(d, "%Y-%m-%d") for d in daily_data.keys()
                    )
                except Exception:
                    # Skip malformed date keys
                    continue

                start = date_objs[0]
                end = date_objs[-1]

                # Align to Monday for the first week to compute
                current = start - timedelta(days=start.weekday())  # Monday
                while current <= end:
                    week_start = current  # Monday
                    week_end = week_start + timedelta(days=6)  # Sunday

                    y = week_start.strftime("%Y")
                    m = week_start.strftime("%m")
                    # "nth week of month" (1–5) using the Monday's day-of-month
                    w = f"{((week_start.day - 1) // 7) + 1:02d}"

                    # Sum total_kWh for the 7 days in this Monday–Sunday window
                    total_kwh_week = 0.0
                    for i in range(7):
                        d_key = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
                        if d_key in daily_data:
                            try:
                                total_kwh_week += float(
                                    daily_data[d_key].get("total_kWh", 0.0)
                                )
                            except Exception:
                                pass

                    if total_kwh_week > 0:
                        payload = {
                            "total_kWh": round(total_kwh_week, 6),
                            "start_date": week_start.strftime("%Y-%m-%d"),
                            "end_date": week_end.strftime("%Y-%m-%d"),
                            # 👇 updated_at is the Monday of that bucket at 00:05:00
                            "updated_at": f"{week_start.strftime('%Y-%m-%d')} 00:05:00",
                        }

                        ref = db.reference(
                            f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
                        )
                        ref.set(payload)
                        print(
                            f"✅ {user_id}/{device_id}/{appliance_name} → {y}-{m} W{w}: {payload}"
                        )

                    current += timedelta(days=7)

    print("🎉 Weekly backfill complete.")


import pandas as pd
from prophet import Prophet


def backfill_predictions(json_file, min_days=7, output_file="predictions.json"):
    with open(json_file, "r") as f:
        data = json.load(f)

    predictions = {}

    for user_id, devices in data.items():
        predictions[user_id] = {}
        for device_id, appliances in devices.items():
            predictions[user_id][device_id] = {}

            for appliance_name, daily_data in appliances.items():
                sorted_dates = sorted(daily_data.keys())
                rows = [
                    {"ds": d, "y": float(daily_data[d].get("total_kWh", 0))}
                    for d in sorted_dates
                    if daily_data[d].get("total_kWh", 0) > 0
                ]

                if len(rows) < min_days:
                    continue  # not enough data to train

                df = pd.DataFrame(rows)
                df["ds"] = pd.to_datetime(df["ds"])

                appliance_predictions = {}

                # Sliding window: predict day by day until last actual
                for i in range(min_days, len(sorted_dates)):
                    train_dates = sorted_dates[:i]
                    train_rows = [
                        {"ds": d, "y": float(daily_data[d].get("total_kWh", 0))}
                        for d in train_dates
                        if daily_data[d].get("total_kWh", 0) > 0
                    ]

                    if len(train_rows) < min_days:
                        continue

                    train_df = pd.DataFrame(train_rows)
                    train_df["ds"] = pd.to_datetime(train_df["ds"])

                    model = Prophet(daily_seasonality=True)
                    model.fit(train_df)

                    next_day = pd.to_datetime(sorted_dates[i]).date()

                    future = pd.DataFrame({"ds": [pd.to_datetime(next_day)]})
                    forecast = model.predict(future)
                    pred = forecast.iloc[0]

                    appliance_predictions[next_day.isoformat()] = {
                        "horizon": "D0",
                        "model": "Prophet",
                        "predicted_kWh": round(pred["yhat"], 2),
                        "timestamp": datetime.now().isoformat(),
                    }

                predictions[user_id][device_id][appliance_name] = appliance_predictions

    # Save backfill to JSON
    with open(output_file, "w") as f:
        json.dump(predictions, f, indent=4)

    print(f"✅ Backfilled predictions exported to {output_file}")
    return predictions


import pprint

if __name__ == "__main__":
    # hourly_summary_update()
    # backfill_single_day_usage(
    #     input_file="files/fan_23.json",
    #     target_date="2025-09-23",
    #     user_id="tVD45VkzSUhwDwpa3yRES71Wxar2",
    #     device_id="d8bc24124b00",
    #     appliance_name="Fan",
    # )
    preds = backfill_predictions("daily_summary.json")
    pprint.pprint(preds)
    # backfill_weekly_from_export("files/all_daily_summary.json")
    # backfill_multi_day_usage(
    #     input_file="usage1.json",  # your file with {"2025-08-01": {...}, "2025-08-02": {...}}
    #     user_id="tVD45VkzSUhwDwpa3yRES71Wxar2",
    #     device_id="d8bc24124b00",
    #     appliance_name="Fan",
    # )
