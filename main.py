import os
import smtplib
import random
import pandas as pd

from dotenv import load_dotenv
from typing import List
from pydantic import BaseModel, EmailStr
from fastapi import FastAPI, Request, Response, HTTPException, Query
from firebase_admin import credentials, db, initialize_app, firestore, auth
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from pytz import timezone
from prophet import Prophet
from email.mime.text import MIMEText

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
PH_TZ = timezone("Asia/Manila")

cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(
    cred,
    {
        "databaseURL": "https://capstone-238eb-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)

fs = firestore.client()
app = FastAPI()


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

    usage_root = db.reference("/usage").get()
    if not usage_root:
        print("⚠️ No usage data.")
        return

    for user_id, devices in (usage_root or {}).items():
        for device_id, appliances in (devices or {}).items():
            for appliance_name, dates in (appliances or {}).items():
                day_data = (dates or {}).get(today)
                if not day_data:
                    continue

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

                prev_total = float(existing.get("total_kWh", 0.0))
                new_total = prev_total + total_kwh_hour

                daily_ref.update(
                    {
                        "total_kWh": round(new_total, 6),
                        "avg_power": round(avg_power_hour, 2),
                        "max_power": max(
                            float(existing.get("max_power", 0)), max_power_hour
                        ),
                        f"hourly/{hour_key}": round(total_kwh_hour, 6),
                        "updated_at": now_ph.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                print(
                    f"{user_id}/{device_id}/{appliance_name}/{today}/{total_kwh_hour}"
                )

    print("✅ Hourly summary update completed.")


def summary_aggregation():
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")
    target_date = (now_ph - timedelta(days=1)).strftime("%Y-%m-%d")  # yesterday
    interval_seconds = 5

    is_monday = now_ph.weekday() == 0
    is_first_of_month = now_ph.day == 1

    print("📊 Starting summary aggregation...")

    usage_root = db.reference("/usage").get()
    if not usage_root:
        print("⚠️ No usage data.")
        return

    for user_id, devices in (usage_root or {}).items():
        for device_id, appliances in (devices or {}).items():
            for appliance_name, dates in (appliances or {}).items():
                day_data = (dates or {}).get(target_date)
                if not day_data:
                    continue

                powers = [float(rec.get("power", 0)) for rec in day_data.values()]
                if not powers:
                    continue

                total_kwh = sum(
                    (p / 1000.0) * (interval_seconds / 3600.0) for p in powers
                )
                avg_power = sum(powers) / len(powers)
                max_power = max(powers)

                db.reference(
                    f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
                ).update(
                    {
                        "total_kWh": round(total_kwh, 6),
                        "avg_power": round(avg_power, 2),
                        "max_power": round(max_power, 2),
                        "updated_at": now_str,
                    }
                )

    if is_monday:
        prev_week_end = now_ph - timedelta(days=1)
        prev_week_start = prev_week_end - timedelta(days=6)
        y = str(prev_week_start.year)
        m = f"{prev_week_start.month:02d}"
        w = f"{((prev_week_start.day - 1) // 7) + 1:02d}"
        days = [
            (prev_week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)
        ]

        for user_id, devices in (usage_root or {}).items():
            for device_id, appliances in (devices or {}).items():
                for appliance_name in (appliances or {}).keys():
                    total_kwh_week = 0.0
                    for d in days:
                        summary = db.reference(
                            f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{d}"
                        ).get()
                        if summary:
                            total_kwh_week += float(summary.get("total_kWh", 0.0))

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

    if is_first_of_month:
        prev_month_dt = now_ph - timedelta(days=1)
        y, m = str(prev_month_dt.year), f"{prev_month_dt.month:02d}"
        month_prefix = f"{y}-{m}"

        for user_id, devices in (usage_root or {}).items():
            for device_id, appliances in (devices or {}).items():
                for appliance_name in (appliances or {}).keys():
                    total_kwh_month = 0.0
                    daily_branch = (
                        db.reference(
                            f"/daily_summary/{user_id}/{device_id}/{appliance_name}"
                        ).get()
                        or {}
                    )
                    for d, summary in daily_branch.items():
                        if isinstance(d, str) and d.startswith(month_prefix):
                            total_kwh_month += float(summary.get("total_kWh", 0.0))

                    db.reference(
                        f"/monthly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}"
                    ).set(
                        {
                            "total_kWh": round(total_kwh_month, 6),
                            "updated_at": now_str,
                        }
                    )

    print("✅ Aggregation completed (Daily + conditional Weekly/Monthly).")


def total_energy_consumption():
    now_ph = datetime.now(PH_TZ)
    now_str = now_ph.strftime("%Y-%m-%d %H:%M:%S")
    target_dt = now_ph - timedelta(days=1)  # yesterday
    target_date = target_dt.strftime("%Y-%m-%d")
    is_monday = now_ph.weekday() == 0
    y = str((now_ph - timedelta(days=1)).year)
    m = f"{(now_ph - timedelta(days=1)).month:02d}"

    print("📊 Calculating totals...")

    # ---- DAILY TOTAL (for yesterday) ----
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
scheduler.add_job(summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
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
    print(EMAIL_ADDRESS)
    subject = "Your WisEnergy Password Reset Code"
    body = f"Your reset code: {otp}\nIt will expire in 5 minutes"

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = EMAIL_ADDRESS
    message["To"] = to_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(message)
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
def predict_daily_appliance_kwh(user_id: str, device_id: str, appliance_name: str):
    try:
        result = appliance_daily_prediction(user_id, device_id, appliance_name)
        if result is None:
            raise HTTPException(
                status_code=400, detail="Not enough data for prediction."
            )
        return round(result, 2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
