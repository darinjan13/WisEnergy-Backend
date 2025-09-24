import os
import smtplib
import random
import pandas as pd

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
from typing import List
from pydantic import BaseModel, EmailStr
from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials, db, initialize_app, firestore, auth
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from pytz import timezone
from prophet import Prophet
from email.mime.text import MIMEText

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
PH_TZ = timezone("Asia/Manila")

cred = credentials.Certificate("serviceAccount.json")
initialize_app(
    cred,
    {
        # "databaseURL": "https://capstone-238eb-default-rtdb.asia-southeast1.firebasedatabase.app/"
        "databaseURL": "https://wisenergy-11737-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)

fs = firestore.client()
app = FastAPI()

origins = [
    "http://localhost:5173",  # your Vite dev server
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OTPRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    email: str
    new_password: str


def hourly_summary_update():
    now_ph = datetime.now(PH_TZ)
    today = now_ph.strftime("%Y-%m-%d")
    hour_key = now_ph.strftime("%H:00")
    interval_seconds = 5

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

                if not day_data:
                    continue

                powers = []
                for ts, rec in day_data.items():
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
                max_power_hour = max(powers)

                daily_ref = db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{today}"
                )
                existing = daily_ref.get() or {}

                hourly_ref = daily_ref.child("hourly")
                hourly_ref.update({hour_key: round(total_kwh_hour, 6)})
                all_hourly = hourly_ref.get() or {}

                new_total = sum(all_hourly.values())

                hourly_data = existing.get("hourly", {}) or {}
                total_kwh_so_far = sum(hourly_data.values())

                hours_so_far = len(hourly_data)
                avg_power_day = (
                    (total_kwh_so_far * 1000) / hours_so_far if hours_so_far else 0
                )
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

                print(f"{user_id}/{device_id}/{appliance_name}/{today}/{hour_key} ✅")

    print("✅ Hourly summary update completed.")


def summary_aggregation():
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

    daily_root = db.reference("/daily_summary").get() or {}
    for user_id, devices in (daily_root or {}).items():
        for device_id, appliances in (devices or {}).items():
            for appliance_name in (appliances or {}).keys():
                total_kwh_week = 0.0

                # Sum from daily_summary
                for d in days:
                    summary = db.reference(
                        f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{d}"
                    ).get()
                    if summary:
                        total_kwh_week += float(summary.get("total_kWh", 0.0))

                # Save into weekly_summary
                db.reference(
                    f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
                ).set(
                    {
                        "total_kWh": round(total_kwh_week, 6),
                        "start_date": prev_week_start.strftime("%Y-%m-%d"),
                        "end_date": prev_week_end.strftime("%Y-%m-%d"),
                        "updated_at": now_str,
                    }
                )

                print(f"✅ Weekly summary updated for {appliance_name} ({user_id})")

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


def generate_recommendations(user_id: str = None):
    now_ph = datetime.now(PH_TZ)
    today = now_ph.strftime("%Y-%m-%d")
    last_hour_key = (now_ph - timedelta(hours=1)).strftime("%H:00")

    print(f"🤖 Generating recommendations for {today} {last_hour_key}...")

    if user_id:
        # Limit reads to one user only
        user_root = db.reference(f"/daily_summary/{user_id}").get() or {}
        daily_root = {user_id: user_root}
    else:
        daily_root = db.reference("/daily_summary").get() or {}

    recommendations = {}

    for uid, devices in (daily_root or {}).items():
        tips = []

        for device_id, appliances in (devices or {}).items():
            for appliance_name, days in (appliances or {}).items():
                summary = days.get(today)
                if not summary:
                    continue

                hourly = (summary or {}).get("hourly", {})
                last_hour_kwh = float(hourly.get(last_hour_key, 0))

                if last_hour_kwh and last_hour_kwh > 0.5:  # example threshold
                    tips.append(
                        f"⚡ {appliance_name} consumed {last_hour_kwh:.2f} kWh in the last hour."
                    )

                total_kwh = float(summary.get("total_kWh", 0))
                if total_kwh > 5:  # another rule
                    tips.append(
                        f"📊 Your total usage today reached {total_kwh:.2f} kWh already."
                    )

        if tips:
            recommendations[uid] = {
                "tips": tips,
                "generated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                "date": today,
                "hour": last_hour_key,
            }

    print("✅ Recommendations generated.")
    return recommendations


scheduler = BackgroundScheduler()
# scheduler.add_job(summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ)
scheduler.add_job(hourly_summary_update, "cron", minute=0, timezone=PH_TZ)
scheduler.start()


def appliance_daily_prediction(user_id, device_id, appliance_name):
    MIN_DAYS = 7
    daily_ref = db.reference(f"/daily_summary/{user_id}/{device_id}/{appliance_name}")
    daily_data = daily_ref.get()

    if not daily_data or len(daily_data) < MIN_DAYS:
        print("❌ Not enough data.")
        return None

    sorted_dates = sorted(daily_data.keys())
    rows = [
        {"ds": d, "y": float(daily_data[d].get("total_kWh", 0))}
        for d in sorted_dates
        if daily_data[d].get("total_kWh", 0) > 0
    ]
    if len(rows) < MIN_DAYS:
        print("❌ Not enough valid (non-zero) data.")
        return None

    df = pd.DataFrame(rows)

    model = Prophet(daily_seasonality=True)
    model.fit(df)

    future = model.make_future_dataframe(periods=1)
    forecast = model.predict(future)

    prediction = forecast.iloc[-1]
    predicted_kwh = round(prediction["yhat"], 2)

    print(f"Predicted kwh for tomorrow: {predicted_kwh}")
    return predicted_kwh


def generate_otp_code():
    return f"{random.randint(10000, 99999)}"


def send_otp_email(to_email: str, otp: str):
    subject = "Your WisEnergy Password Reset Code"
    body = f"Your reset code: {otp}\nIt will expire in 5 minutes"

    message = Mail(
        from_email=EMAIL_ADDRESS,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body,
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email send failed: {str(e)}")


def split_name(full_name: str):
    if not full_name:
        return None, None

    parts = full_name.strip().split()

    if len(parts) == 1:
        return parts[0], ""
    else:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
        return first_name, last_name


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


@app.get("/generate-reccomendations")
def recommendations(user_id: str = Query(None)):
    """
    Generate recommendations.
    - If user_id provided: only process that user.
    - Else: process all users.
    """
    recs = generate_recommendations(user_id=user_id)
    return {"status": "ok", "recommendations": recs}


@app.get("/devices")
def get_devices():
    devices_ref = db.reference("/devices")
    devices_data = devices_ref.get()
    if not devices_data:
        return []
    return list(devices_data.keys())


@app.get("/users", response_model=List[dict])
def get_all_users():
    users = []
    page = auth.list_users()
    while page:
        for user in page.users:
            if user.email and user.email.endswith("@gmail.com"):
                first_name, last_name = split_name(user.display_name)
                users.append(
                    {
                        "uid": user.uid,
                        "email": user.email,
                        "first_name": first_name,
                        "last_name": last_name,
                        "password": user.password_hash,
                        "last_sign_in": user.user_metadata.last_sign_in_timestamp,
                        "created_at": user.user_metadata.creation_timestamp,
                    }
                )
        page = page.get_next_page()
    return users


@app.post("/reset-password")
def reset_password(data: PasswordResetRequest):
    try:
        user = auth.get_user_by_email(data.email)
        auth.update_user(user.uid, password=data.new_password)
        return {"message": "Password updated Successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/verify-email")
def verify_email(req: OTPRequest):
    return


@app.post("/generate-otp")
def generate_otp(req: OTPRequest):
    print(f"{req.email}")
    try:
        auth.get_user_by_email(req.email)
    except auth.UserNotFoundError:
        raise HTTPException(
            status_code=500, detail=f"{req.email} is not yet registered."
        )
    email_id = req.email.replace(".", "_")
    otp = generate_otp_code()
    expires = datetime.utcnow() + timedelta(minutes=5)
    fs.collection("otp-verification").document(email_id).set(
        {"otp": otp, "expires_at": expires.isoformat(), "verified": False}
    )
    send_otp_email(req.email, otp)

    return {"message": f"OTP sent to {req.email}"}


@app.get("/predict/{user_id}/{device_id}/{appliance_name}")
def predict_and_return_history(user_id: str, device_id: str, appliance_name: str):
    try:
        today = datetime.now().date().strftime("%Y-%m-%d")

        ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/{today}"
        )
        existing = ref.get()

        if not existing:
            result = appliance_daily_prediction(user_id, device_id, appliance_name)
            if result is None:
                raise HTTPException(
                    status_code=400, detail="Not enough data for prediction."
                )

            predicted_kwh = round(result, 2)
            payload = {
                "predicted_kWh": predicted_kwh,
                "timestamp": datetime.now().isoformat(),
                "model": "Prophet",
                "horizon": "D0",
            }
            ref.set(payload)

        pred_ref = db.reference(f"/predictions/{user_id}/{device_id}/{appliance_name}")
        all_preds = pred_ref.get() or {}

        dates = sorted(all_preds.keys())[-5:]
        past5 = {d: all_preds[d] for d in dates}

        return {"predictions": past5}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


import json


def parse_time_key(date_str, time_str):
    """Convert 'YYYY-MM-DD', 'HH_MM_SS' to datetime"""
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H_%M_%S")


def compute_daily_summary(date, readings):
    if not readings:
        return None

    # Sort readings by time
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

    return {
        "avg_power": round(avg_power, 2),
        "hourly": {h: round(v, 6) for h, v in hourly.items()},
        "max_power": round(max_power, 2),
        "total_kWh": round(total_kWh, 5),
        "updated_at": updated_at,
    }


@app.get("/process-fan")
def process_fan():
    try:
        with open("fridge.json") as f:  # your merged Aug+Sept file
            raw_data = json.load(f)

        processed = {}

        for date, times in raw_data.items():
            readings = []
            for time_str, record in times.items():
                if "power" not in record:
                    continue
                t = parse_time_key(date, time_str)
                readings.append((t, record["power"]))

            daily_summary = compute_daily_summary(date, readings)
            if daily_summary:
                processed[date] = daily_summary

        # Save processed results
        with open("fridge_processed.json", "w") as f:
            json.dump(processed, f, indent=2)

        return {
            "status": "success",
            "message": "Processed data saved as fan_usage_processed.json",
            "days_processed": len(processed),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def rolling_backfill_predictions_with_regressors(
    daily_json: dict, start_date: str, out_file: str = None
):
    """
    Backfills predictions starting from `start_date` using Prophet with regressors.
    Uses data before each target date as training.
    Returns dict in Firebase format.
    """
    all_dates = sorted(daily_json.keys())
    start_idx = all_dates.index(start_date)

    results = {}

    for i in range(start_idx, len(all_dates)):
        target_date = all_dates[i]

        # training set = all dates before target_date
        train_dates = all_dates[:i]
        if len(train_dates) < 2:
            continue

        records = []
        for d in train_dates:
            try:
                total_kwh = float(daily_json[d].get("total_kWh", 0))
                avg_power = float(daily_json[d].get("avg_power", 0))
                max_power = float(daily_json[d].get("max_power", 0))

                records.append(
                    {
                        "ds": datetime.strptime(d, "%Y-%m-%d"),
                        "y": total_kwh,
                        "avg_power": avg_power,
                        "max_power": max_power,
                    }
                )
            except Exception:
                continue

        df = pd.DataFrame(records).sort_values("ds")

        # train Prophet with regressors
        model = Prophet(daily_seasonality=True, yearly_seasonality=True)
        model.add_regressor("avg_power")
        model.add_regressor("max_power")
        model.fit(df)

        # Prepare future for the target_date
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        future = pd.DataFrame(
            {
                "ds": [target_dt],
                "avg_power": [daily_json[target_date].get("avg_power", 0)],
                "max_power": [daily_json[target_date].get("max_power", 0)],
            }
        )

        forecast = model.predict(future).iloc[0]

        results[target_date] = {
            "predicted_kWh": round(float(forecast["yhat"]), 2),
            "timestamp": forecast["ds"].strftime("%Y-%m-%dT%H:%M:%S"),
        }

        print(
            f"✅ Forecasted {target_date}: {results[target_date]['predicted_kWh']} kWh"
        )

    # optional save
    if out_file:
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)

    return results


@app.get("/qwe")
def backfill_predictions():
    with open("fan_usage_processed.json", "r") as f:
        fan_data = json.load(f)

    preds = rolling_backfill_predictions_with_regressors(
        fan_data, start_date="2025-08-14", out_file="fan_predictions.json"
    )
