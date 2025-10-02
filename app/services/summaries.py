from datetime import datetime, timedelta
from ..utils.firebase import db
from ..utils.timezone import PH_TZ
from .notifications import notify_user


def hourly_summary_update():
    now_ph = datetime.now(PH_TZ)
    # Process the previous hour
    prev_hour = now_ph - timedelta(hours=1)
    today = prev_hour.strftime(
        "%Y-%m-%d"
    )  # Previous hour’s date, e.g., "2025-09-30" at 00:00
    hour_key = prev_hour.strftime("%H:00")  # e.g., "23:00" at 00:00

    # Determine week based on previous hour (Monday to Sunday)
    current_day = prev_hour.weekday()
    week_start = prev_hour - timedelta(days=current_day)  # Monday of this week
    week_end = week_start + timedelta(days=6)  # Sunday of this week
    y = str(week_start.year)
    m = f"{week_start.month:02d}"
    w = f"{((week_start.day - 1) // 7) + 1:02d}"

    print(f"📊 Running hourly summary update for {today} {hour_key}...")

    users = db.reference("/usage").get(shallow=True)
    if not users:
        print("⚠️ No usage data.")
        return

    for user_id in users:
        devices = db.reference(f"/usage/{user_id}").get(shallow=True) or {}
        for device_id in devices:
            appliances = (
                db.reference(f"/usage/{user_id}/{device_id}").get(shallow=True) or {}
            )
            for appliance_name in appliances:
                day_data = (
                    db.reference(
                        f"/usage/{user_id}/{device_id}/{appliance_name}/{today}"
                    ).get()
                    or {}
                )

                # Collect powers + timestamps for the previous hour
                records = []
                for ts, rec in day_data.items():
                    try:
                        ts_dt = datetime.strptime(ts, "%H_%M_%S")
                        if ts_dt.hour == prev_hour.hour:
                            p = float(rec.get("power", 0))
                            records.append((ts_dt, p))
                    except:
                        continue

                if len(records) < 2:
                    continue  # Need at least 2 points for intervals

                records.sort(key=lambda x: x[0])
                total_kwh_hour = 0.0
                powers = []

                # Calculate energy by actual intervals
                for i in range(len(records) - 1):
                    t1, p1 = records[i]
                    t2, _ = records[i + 1]
                    dt_hr = (t2 - t1).total_seconds() / 3600
                    total_kwh_hour += (p1 * dt_hr) / 1000
                    powers.append(p1)

                max_power_hour = max(powers)

                daily_ref = db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{today}"
                )
                existing = daily_ref.get() or {}

                # Prevent double-counting if hour already processed
                hourly_ref = daily_ref.child("hourly")
                all_hourly = hourly_ref.get() or {}
                if hour_key in all_hourly and all_hourly[hour_key] == round(
                    total_kwh_hour, 6
                ):
                    print(
                        f"ℹ️ Skipping update for {appliance_name}: Hour {hour_key} already processed"
                    )
                    continue

                # Update hourly bucket
                try:
                    hourly_ref.update({hour_key: round(total_kwh_hour, 6)})
                except Exception as e:
                    print(f"⚠️ Failed to update hourly data for {appliance_name}: {e}")
                    continue

                # Recompute daily totals
                all_hourly = hourly_ref.get() or {}
                new_total = sum(all_hourly.values())

                # Daily average power across all day's readings
                all_powers = [float(r.get("power", 0)) for r in day_data.values()]
                avg_power_day = sum(all_powers) / len(all_powers) if all_powers else 0

                try:
                    daily_ref.update(
                        {
                            "total_kWh": round(new_total, 6),
                            "avg_power": round(avg_power_day, 2),
                            "max_power": max(
                                float(existing.get("max_power", 0)), max_power_hour
                            ),
                            "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                except Exception as e:
                    print(f"⚠️ Failed to update daily_summary for {appliance_name}: {e}")
                    continue

                print(
                    f"✅ {appliance_name} {today} {hour_key}: "
                    f"{len(records)} pts, avg={round(avg_power_day,1)}W, kWh={round(total_kwh_hour,4)}"
                )

                # Update weekly_summary
                weekly_ref = db.reference(
                    f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
                )
                try:
                    existing_weekly = weekly_ref.get() or {}
                    existing_kwh = float(existing_weekly.get("total_kWh", 0.0))
                    new_kwh = existing_kwh + total_kwh_hour

                    # Cap end_date at week_end (Sunday)
                    end_date = min(today, week_end.strftime("%Y-%m-%d"))

                    weekly_ref.set(
                        {
                            "total_kWh": round(new_kwh, 6),
                            "start_date": week_start.strftime("%Y-%m-%d"),
                            "end_date": end_date,
                            "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

                    print(
                        f"📅 Weekly summary updated for {appliance_name} ({user_id}): "
                        f"Week {y}-{m}-W{w}, total_kWh={round(new_kwh, 4)}, start_date={week_start.strftime('%Y-%m-%d')}, end_date={end_date}"
                    )
                except Exception as e:
                    print(
                        f"⚠️ Failed to update weekly_summary for {appliance_name}: {e}"
                    )

    for user_id in users:
        notify_user(
            uid=user_id,
            title="WisEnergy Update ⚡",
            body=f"Your energy summary for {today} {hour_key} is updated.",
            data={"screen": "dashboard", "date": today, "hour": hour_key},
        )

    print("🎉 Hourly and weekly summary update completed.")


def weekly_summary_aggregation():
    """
    Aggregate daily_summary into weekly_summary for the previous week (Monday to Sunday),
    running on Mondays. Always create a weekly_summary entry for each user/device/appliance,
    even if no daily_summary data exists (total_kWh = 0.0).
    """
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")

    # Only run weekly aggregation on Mondays
    if now_ph.weekday() != 0:
        print("⚠️ Not Monday, skipping weekly aggregation.")
        return

    prev_week_end = now_ph - timedelta(days=1)  # Sunday
    prev_week_start = prev_week_end - timedelta(days=6)  # Monday
    y = str(prev_week_start.year)
    m = f"{prev_week_start.month:02d}"
    w = f"{((prev_week_start.day - 1) // 7) + 1:02d}"

    # Collect all days in last week
    days = [
        (prev_week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)
    ]

    print(f"📊 Starting weekly aggregation for {days[0]} → {days[-1]}")

    # Get all users, devices, and appliances from /appliances or /daily_summary
    appliances_root = db.reference("/appliances").get() or {}
    daily_root = db.reference("/daily_summary").get() or {}

    # Combine user/device/appliance combinations from both paths
    combinations = set()
    for user_id, devices in appliances_root.items():
        for device_id, appliances in devices.items():
            for appliance_name in appliances.keys():
                combinations.add((user_id, device_id, appliance_name))
    for user_id, devices in daily_root.items():
        for device_id, appliances in devices.items():
            for appliance_name in appliances.keys():
                combinations.add((user_id, device_id, appliance_name))

    if not combinations:
        print("⚠️ No appliances found for aggregation.")
        return

    for user_id, device_id, appliance_name in combinations:
        total_kwh_week = 0.0

        # Sum from daily_summary
        for d in days:
            summary = db.reference(
                f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{d}"
            ).get()
            if summary:
                try:
                    total_kwh_week += float(summary.get("total_kWh", 0.0))
                except (ValueError, TypeError):
                    continue

        # Save into weekly_summary, even if total_kWh is 0.0
        weekly_ref = db.reference(
            f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
        )
        try:
            weekly_ref.set(
                {
                    "total_kWh": round(total_kwh_week, 6),
                    "start_date": prev_week_start.strftime("%Y-%m-%d"),
                    "end_date": prev_week_end.strftime("%Y-%m-%d"),
                    "updated_at": now_str,
                }
            )
            print(
                f"✅ Weekly summary updated for {appliance_name} ({user_id}): total_kWh={round(total_kwh_week, 6)}"
            )
        except Exception as e:
            print(
                f"⚠️ Failed to update weekly_summary for {appliance_name} ({user_id}): {e}"
            )
            continue

    print("🎉 Weekly aggregation completed.")


def total_energy_consumption():
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")
    target_dt = now_ph - timedelta(days=1)
    target_date = target_dt.strftime("%Y-%m-%d")
    is_monday = now_ph.weekday() == 0
    y = str((now_ph - timedelta(days=1)).year)
    m = f"{(now_ph - timedelta(days=1)).month:02d}"

    print("📊 Calculating totals...")

    daily_root = db.reference("/daily_summary").get() or {}
    for user_id, devices in daily_root.items():
        total_kwh_daily = 0.0
        for device in (devices or {}).values():
            for appliance in (device or {}).values():
                summary = (appliance or {}).get(target_date)
                if summary:
                    total_kwh_daily += float(summary.get("total_kWh", 0.0))

        db.reference(f"/daily_total_consumption/{user_id}/{target_date}").set(
            {
                "total_energy_consumption": round(total_kwh_daily, 2),
                "updated_at": now_str,
            }
        )
        monthly_total = (
            db.reference(
                f"/monthly_total_consumption/{user_id}/{y}/{m}/total_energy_consumption"
            ).get()
            or 0
        )

        db.reference(f"/monthly_total_consumption/{user_id}/{y}/{m}").update(
            {
                "total_energy_consumption": round(monthly_total + total_kwh_daily, 2),
                "updated_at": now_str,
            }
        )

    # ---- WEEKLY TOTAL (previous Mon–Sun; Monday-owned bucket) ----
    if is_monday:
        prev_week_end = now_ph - timedelta(days=1)  # Sunday (yesterday)
        prev_week_start = prev_week_end - timedelta(days=6)  # Monday of last week
        yw = str(prev_week_start.year)
        mw = f"{prev_week_start.month:02d}"
        ww = f"{((prev_week_start.day - 1) // 7) + 1:02d}"

        weekly_root = db.reference("/weekly_summary").get() or {}
        for user_id, devices in weekly_root.items():
            user_total = 0.0
            for device_vals in (devices or {}).values():
                for appl_vals in (device_vals or {}).values():
                    bucket = (appl_vals or {}).get(yw, {}).get(mw, {}).get(ww)
                    if bucket:
                        user_total += float(bucket.get("total_kWh", 0.0))

            db.reference(f"/weekly_total_consumption/{user_id}/{yw}/{mw}/{ww}").set(
                {"total_energy_consumption": round(user_total, 2)}
            )

    print("✅ Totals updated (Daily + conditional Weekly + Monthly MTD).")
