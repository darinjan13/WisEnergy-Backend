from datetime import datetime, timedelta
from ..utils.firebase import db
from ..utils.timezone import PH_TZ
from .notifications import notify_user


def hourly_summary_update():
    now_ph = datetime.now(PH_TZ)
    prev_hour = now_ph - timedelta(hours=1)
    today = prev_hour.strftime("%Y-%m-%d")
    hour_key = prev_hour.strftime("%H:00")

    # Week bucket
    current_day = prev_hour.weekday()
    week_start = prev_hour - timedelta(days=current_day)
    week_end = week_start + timedelta(days=6)
    y = str(week_start.year)
    m = f"{week_start.month:02d}"
    w = f"{((week_start.day - 1) // 7) + 1:02d}"

    # Month bucket
    month_start = prev_hour.replace(day=1)
    y_month = str(month_start.year)
    m_month = f"{month_start.month:02d}"

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

                # Collect powers + timestamps for prev hour
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
                    continue

                records.sort(key=lambda x: x[0])
                total_kwh_hour = 0.0
                powers = []

                for i in range(len(records) - 1):
                    t1, p1 = records[i]
                    t2, _ = records[i + 1]
                    dt_hr = (t2 - t1).total_seconds() / 3600
                    total_kwh_hour += (p1 * dt_hr) / 1000
                    powers.append(p1)

                max_power_hour = max(powers)

                # --- DAILY SUMMARY ---
                daily_ref = db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{today}"
                )
                existing = daily_ref.get() or {}

                hourly_ref = daily_ref.child("hourly")
                all_hourly = hourly_ref.get() or {}
                if hour_key in all_hourly and all_hourly[hour_key] == round(
                    total_kwh_hour, 6
                ):
                    print(f"ℹ️ Skipping {appliance_name} {hour_key}, already processed.")
                    continue

                try:
                    hourly_ref.update({hour_key: round(total_kwh_hour, 6)})
                except Exception as e:
                    print(f"⚠️ Failed hourly update {appliance_name}: {e}")
                    continue

                all_hourly = hourly_ref.get() or {}
                new_total = sum(all_hourly.values())

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
                    print(f"⚠️ Failed daily_summary {appliance_name}: {e}")
                    continue

                print(
                    f"✅ {appliance_name} {today} {hour_key}: kWh={round(total_kwh_hour,4)}"
                )

                # --- WEEKLY SUMMARY ---
                weekly_ref = db.reference(
                    f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
                )
                try:
                    existing_weekly = weekly_ref.get() or {}
                    existing_kwh = float(existing_weekly.get("total_kWh", 0.0))
                    new_kwh = existing_kwh + total_kwh_hour
                    end_date = min(today, week_end.strftime("%Y-%m-%d"))

                    weekly_ref.set(
                        {
                            "total_kWh": round(new_kwh, 6),
                            "start_date": week_start.strftime("%Y-%m-%d"),
                            "end_date": end_date,
                            "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                except Exception as e:
                    print(f"⚠️ Failed weekly_summary {appliance_name}: {e}")

                # --- MONTHLY SUMMARY ---
                monthly_ref = db.reference(
                    f"/monthly_summary/{user_id}/{device_id}/{appliance_name}/{y_month}/{m_month}"
                )
                try:
                    existing_monthly = monthly_ref.get() or {}
                    existing_kwh = float(existing_monthly.get("total_kWh", 0.0))
                    new_monthly_kwh = round(existing_kwh + total_kwh_hour, 6)

                    # Approximate end of month
                    next_month = month_start.replace(day=28) + timedelta(days=4)
                    month_end = (next_month - timedelta(days=next_month.day)).strftime(
                        "%Y-%m-%d"
                    )

                    monthly_ref.set(
                        {
                            "total_kWh": new_monthly_kwh,
                            "start_date": month_start.strftime("%Y-%m-%d"),
                            "end_date": month_end,
                            "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                except Exception as e:
                    print(f"⚠️ Failed monthly_summary {appliance_name}: {e}")

                # --- APPLIANCE latest_kwh ---
                appliance_ref = db.reference(
                    f"/appliances/{user_id}/{device_id}/{appliance_name}"
                )
                try:
                    appliance_data = appliance_ref.get() or {}
                    prev_total = float(appliance_data.get("latest_kwh", 0.0))
                    appliance_ref.update(
                        {"latest_kwh": round(prev_total + total_kwh_hour, 6)}
                    )
                except Exception as e:
                    print(f"⚠️ Failed latest_kwh update {appliance_name}: {e}")
    should_notify = (prev_hour.hour % 4) == 0
    # Notify all users
    if should_notify:
        for user_id in users:
            title = "WisEnergy Update ⚡"
            body = f"Your energy summary for {today} {hour_key} is updated."

            # send push
            notify_user(
                uid=user_id,
                title=title,
                body=body,
                data={"screen": "dashboard", "date": today, "hour": hour_key},
            )

            # save notification record
            save_notification(user_id, title, body)
    print("🎉 Hourly, weekly, monthly, and latest_kwh update completed.")


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
                {
                    "total_energy_consumption": round(user_total, 2),
                    "updated_at": now_str,
                }
            )

    print("✅ Totals updated (Daily + conditional Weekly + Monthly MTD).")


def save_notification(user_id, title, message):
    try:
        notif_ref = db.reference(f"/notifications/{user_id}")
        notif_ref.push(
            {
                "title": title,
                "message": message,
                "created_at": datetime.now(PH_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "read_at": None,
            }
        )
        print(f"💾 Notification saved for {user_id}")
    except Exception as e:
        print(f"⚠️ Failed to save notification for {user_id}: {e}")
