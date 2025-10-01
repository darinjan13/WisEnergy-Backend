import os
import random
import pandas as pd
import json
import re
import requests

from google import genai
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

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
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
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

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
    userVerification: bool


class PasswordResetRequest(BaseModel):
    email: str
    new_password: str


class User(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    location: str
    role: str


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
            data={"screen": "dashboard", "date": today, "hour": hour_key}
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


def scheduled_prediction_update():
    now = datetime.now(PH_TZ)
    today = now.strftime("%Y-%m-%d")
    week_key = now.strftime("%Y-W%U")

    print(f"🔮 Running scheduled prediction update for {today} / {week_key}...")

    # Fetch all users and devices
    daily_root = db.reference("/daily_summary").get() or {}
    for user_id, devices in daily_root.items():
        for device_id, appliances in (devices or {}).items():
            for appliance_name in (appliances or {}).keys():
                # ---- Daily Prediction ----
                daily_pred = appliance_daily_prediction(
                    user_id, device_id, appliance_name
                )
                if daily_pred:
                    db.reference(
                        f"/predictions/{user_id}/{device_id}/{appliance_name}/daily/{today}"
                    ).set(
                        {
                            "predicted_kWh": daily_pred,
                            "timestamp": now.isoformat(),
                            "model": "Prophet",
                            "horizon": "D0",
                        }
                    )
                    print(f"✅ Daily prediction stored for {appliance_name} ({today})")

                # ---- Weekly Prediction (only on Mondays) ----
                if now.weekday() == 0:  # Monday → run weekly forecast
                    weekly_pred = appliance_weekly_prediction(
                        user_id, device_id, appliance_name
                    )
                    if weekly_pred:
                        db.reference(
                            f"/predictions/{user_id}/{device_id}/{appliance_name}/weekly/{week_key}"
                        ).set(
                            {
                                "predicted_kWh": weekly_pred,
                                "timestamp": now.isoformat(),
                                "model": "Prophet",
                                "horizon": "W0",
                            }
                        )
                        print(
                            f"✅ Weekly prediction stored for {appliance_name} ({week_key})"
                        )


scheduler = BackgroundScheduler()
scheduler.add_job(weekly_summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ)
scheduler.add_job(
    scheduled_prediction_update, "cron", hour=0, minute=20, timezone=PH_TZ
)
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


def appliance_weekly_prediction(user_id, device_id, appliance_name):
    MIN_WEEKS = 4
    weekly_ref = db.reference(f"/weekly_summary/{user_id}/{device_id}/{appliance_name}")
    weekly_data = weekly_ref.get()

    if not weekly_data:
        print("❌ No weekly data.")
        return None

    rows = []
    for year, months in weekly_data.items():
        for month, weeks in months.items():
            for week, summary in weeks.items():
                try:
                    start_date = summary.get("start_date")
                    total_kwh = float(summary.get("total_kWh", 0))
                    if total_kwh > 0 and start_date:
                        rows.append({"ds": start_date, "y": total_kwh})
                except Exception as e:
                    print("⚠️ Error parsing:", e)
                    continue

    if len(rows) < MIN_WEEKS:
        print("❌ Not enough weekly data.")
        return None

    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"])
    df = df.sort_values("ds")

    model = Prophet(weekly_seasonality=True)
    model.fit(df)

    # Predict 1 week ahead
    future = model.make_future_dataframe(
        periods=1, freq="W-MON"
    )  # weekly, start Monday
    forecast = model.predict(future)

    prediction = forecast.iloc[-1]
    predicted_kwh = round(prediction["yhat"], 2)

    print(f"📈 Predicted kWh for next week: {predicted_kwh}")
    return predicted_kwh


def generate_otp_code():
    return f"{random.randint(10000, 99999)}"


def send_otp_email(to_email: str, otp: str, userVerification: bool):
    if userVerification:
        subject = "Verify Your WisEnergy Account"
        body = (
            f"Hello,\n\n"
            f"Thanks for signing up! Please use the following code to verify your account:\n\n"
            f"Verification Code: {otp}\n\n"
            f"This code will expire in 5 minutes.\n\n"
            f"Welcome to WisEnergy!"
        )
    else:
        subject = "Your WisEnergy Password Reset Code"
        body = (
            f"Hello,\n\n"
            f"We received a request to reset your password. Use the code below to proceed:\n\n"
            f"Reset Code: {otp}\n\n"
            f"This code will expire in 5 minutes.\n\n"
            f"If you didn't request this, please ignore this email."
        )

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


@app.get("/devices")
def get_devices():
    devices_ref = db.reference("/devices")
    devices_data = devices_ref.get()
    if not devices_data:
        return []

    # Include ID with each device
    return [{"id": device_id, **details} for device_id, details in devices_data.items()]


@app.get("/users", response_model=List[dict])
def get_all_users():
    # Fetch from Realtime Database
    users_ref = db.reference("/users").get() or {}

    # Fetch from Firebase Auth
    auth_users = {}
    page = auth.list_users()
    while page:
        for user in page.users:
            auth_users[user.uid] = {
                "password": user.password_hash,  # only password from Auth
            }
        page = page.get_next_page()

    # Merge database and auth data
    users = []
    for uid, data in users_ref.items():
        merged = {
            "uid": uid,
            "email": data.get("email"),
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "location": data.get("location"),
            "created_at": data.get("created_at"),
            "role": data.get("role"),
            "password": auth_users.get(uid, {}).get("password"),  # only from Auth
        }
        users.append(merged)

    return users


# Add user
@app.post("/users")
def add_user(user: User):
    try:
        now = datetime.now().strftime("%Y-%m-%d")

        # 1. Create the user in Firebase Authentication
        firebase_user = auth.create_user(
            email=user.email,
            password="WisEnergy2025!",  # 🔐 You may generate a random password or let frontend supply it
            display_name=f"{user.first_name} {user.last_name}",
        )

        # 2. Save to Realtime Database under /users
        ref = db.reference("/users")
        user_id = firebase_user.uid  # use Firebase Auth UID as ID to avoid mismatches

        payload = {
            "id": user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "location": user.location,
            "role": user.role,
            "date_created": now,
            "date_modified": now,
        }

        ref.child(user_id).set(payload)

        return {"status": "success", "data": payload}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/users/{user_id}")
def edit_user(user_id: str, user: User):
    try:
        # Check if exists in DB
        ref = db.reference(f"/users/{user_id}")
        existing = ref.get()
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")

        now = datetime.now().strftime("%Y-%m-%d")

        # 1. Update in Firebase Auth
        auth.update_user(
            user_id,
            email=user.email,
            display_name=f"{user.first_name} {user.last_name}",
        )

        # 2. Update in Realtime Database
        updated_data = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "location": user.location,
            "role": user.role,
            "date_modified": now,
        }
        ref.update(updated_data)

        return {"status": "success", "data": {**existing, **updated_data}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/reviews")
def get_reviews():
    reviews_ref = db.reference("/reviews")
    reviews_data = reviews_ref.get()
    if not reviews_data:
        return []

    return [{"id": review_id, **details} for review_id, details in reviews_data.items()]


@app.get("/reviews/{review_id}")
def get_review(review_id: str):
    review_ref = db.reference(f"/reviews/{review_id}")
    review_data = review_ref.get()
    if not review_data:
        return {"error": "Review not found"}
    return {"id": review_id, **review_data}


@app.get("/feedback")
def get_feedback():
    feedback_ref = db.reference("/feedback")
    feedback_data = feedback_ref.get()
    if not feedback_data:
        return []

    return [
        {"id": feedback_id, **details} for feedback_id, details in feedback_data.items()
    ]


@app.get("/feedback/{feedback_id}")
def get_feedback_item(feedback_id: str):
    feedback_ref = db.reference(f"/feedback/{feedback_id}")
    feedback_data = feedback_ref.get()
    if not feedback_data:
        return {"error": "Feedback not found"}
    return {"id": feedback_id, **feedback_data}


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
    print(f"{req.userVerification}")
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
    send_otp_email(req.email, otp, req.userVerification)

    return {"message": f"OTP sent to {req.email}"}


@app.get("/predict/{user_id}/{device_id}/{appliance_name}")
def predict_and_return_history(user_id: str, device_id: str, appliance_name: str):
    try:
        today = datetime.now().date()

        # ---------- DAILY ----------
        daily_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/daily"
        )
        all_daily = daily_ref.get() or {}

        # find last predicted date if any
        last_pred_date = (
            max(datetime.strptime(d, "%Y-%m-%d").date() for d in all_daily.keys())
            if all_daily
            else None
        )
        start_date = last_pred_date + timedelta(days=1) if last_pred_date else today

        # fill until today
        current = start_date
        while current <= today:
            result = appliance_daily_prediction(user_id, device_id, appliance_name)
            if result is not None:
                payload = {
                    "predicted_kWh": round(result, 2),
                    "timestamp": f"{current.strftime('%Y-%m-%d')} 00:05:00",
                    "model": "Prophet",
                    "horizon": "D0",
                }
                daily_ref.child(current.isoformat()).set(payload)
            current += timedelta(days=1)

        all_daily = daily_ref.get() or {}
        last5_daily = {d: all_daily[d] for d in sorted(all_daily.keys())[-5:]}

        # ---------- WEEKLY ----------
        now = datetime.now()
        current_week = f"{((now.day - 1) // 7) + 1:02d}"
        y, m = str(now.year), f"{now.month:02d}"

        weekly_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/weekly"
        )
        all_weekly = weekly_ref.get() or {}

        # flatten existing
        flat_weeks = []
        for yy, months in (all_weekly or {}).items():
            for mm, weeks in (months or {}).items():
                for ww, payload in (weeks or {}).items():
                    flat_weeks.append((int(yy), int(mm), int(ww), payload))
        flat_weeks.sort(key=lambda x: (x[0], x[1], x[2]))

        # last existing week
        last_week = flat_weeks[-1] if flat_weeks else None
        # compute current bucket
        target_week = (now.year, now.month, int(current_week))

        # fill gaps up to current week
        if not last_week or (last_week[0], last_week[1], last_week[2]) < target_week:
            result = appliance_weekly_prediction(user_id, device_id, appliance_name)
            if result is not None:
                payload = {
                    "predicted_kWh": round(result, 2),
                    "timestamp": f"{now.strftime('%Y-%m-%d')} 00:05:00",
                    "model": "Prophet",
                    "horizon": "W0",
                }
                weekly_ref.child(str(now.year)).child(f"{now.month:02d}").child(
                    current_week
                ).set(payload)

        # reload weekly
        all_weekly = weekly_ref.get() or {}
        flat_weeks = []
        for yy, months in (all_weekly or {}).items():
            for mm, weeks in (months or {}).items():
                for ww, payload in (weeks or {}).items():
                    flat_weeks.append((int(yy), int(mm), int(ww), payload))
        flat_weeks.sort(key=lambda x: (x[0], x[1], x[2]))

        last5_weekly = [
            {"year": yy, "month": f"{mm:02d}", "week": f"{ww:02d}", "data": payload}
            for yy, mm, ww, payload in flat_weeks[-5:]
        ]

        return {"daily": last5_daily, "weekly": last5_weekly}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def generate_recommendation(user_data: dict):
    """
    Use Gemini API to generate AI-based recommendations based on energy consumption data.
    """
    prompt = f"""
        Given the energy consumption data: {json.dumps(user_data)},
        provide a JSON response with:
        1. "peaks": always Identify peak time(), peak kWh and use the appliance name as keys (ignore appliances with no data for today) and dont use device.
        2. "recommendations": analyze the usage and List at least 3 concise recommendations to reduce energy usage (2-3 sentences each) message only no title.
        3. "insights": List at least 3 concise analysis base on the usage data (1-2 sentences each) message only no title.
        Ensure recommendations are practical, and avoid mentioning products.
    """

    try:
        response = client_gemini.models.generate_content(
            # model="gemini-2.5-pro",
            # model="gemini-2.5-flash",
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )

        # Clean the response text (remove ```json and ``` markers)
        cleaned_response = re.sub(r"^```json\n|```$", "", response.text).strip()
        # Attempt to parse the cleaned response as
        try:
            data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return {"peaks": [], "recommendations": [], "insights": []}

        # Check if the parsed data is a dictionary as expected
        if isinstance(data, dict):
            if "peaks" in data:
                # Standardize peak fields by iterating through each appliance
                peaks = data["peaks"]
                standardized_peaks = []
                for appliance, peak in peaks.items():
                    standardized_peaks.append(
                        {
                            "appliance": appliance,
                            "hour": peak.get("peak_time", peak.get("hour"))
                            or peak.get("peak_hour"),
                            "kWh": peak.get("peak_kWh", peak.get("kWh"))
                            or peak.get("peak_kwh"),
                        }
                    )
                data["peaks"] = standardized_peaks

            return data
        else:
            print(f"Error: Expected a dictionary, but got {type(data)}")
            return {"peaks": [], "recommendations": [], "insights": []}

    except Exception as e:
        print(f"Error generating recommendation with Gemini: {e}")
        return {"peaks": [], "recommendations": [], "insights": []}


@app.get("/generate-recommendations/{user_id}/{date}")
async def get_recommendations(user_id: str, date: datetime):
    """
    Endpoint to generate recommendations for the given user_id and date.
    Falls back to rule-based logic only if Gemini API fails.
    """
    # Fetch user data once
    user_data = fetch_user_data(user_id, date)

    # Generate AI-based recommendations (or empty dict on failure)
    ai_recommendations = generate_recommendation(user_data)

    # Initialize peaks and tips based on Gemini, fallback to rules if Gemini fails
    now_ph = datetime.now(PH_TZ)  # 4:43 PM PHT, Saturday, September 27, 2025
    today = now_ph.strftime("%Y-%m-%d")
    budget_ref = db.reference(
        f"/user_monthly_budget/{user_id}/{now_ph.year}/{now_ph.month:02d}/budget_kwh"
    )
    monthly_budget = budget_ref.get() or 0.0
    daily_budget = monthly_budget / 30 if monthly_budget else float("inf")
    peaks = ai_recommendations.get("peaks", [])
    tips = (
        [
            {"priority": "low", "message": rec}
            for rec in ai_recommendations.get("recommendations", [])
        ]
        if ai_recommendations
        else []
    )
    recommendations = ai_recommendations.get("recommendations", [])
    insights = ai_recommendations.get("insights", [])
    budget_alerts = []

    # Only apply rule-based logic if Gemini failed (ai_recommendations is empty)
    if not ai_recommendations or not any(ai_recommendations.values()):

        last_hour_key = (now_ph - timedelta(hours=1)).strftime("%H:00")  # "15:00"

        rule_based_tips = []
        rule_based_peaks = []

        # Fetch budget and monthly consumption

        monthly_total_ref = db.reference(
            f"/monthly_total_consumption/{user_id}/{now_ph.year}/{now_ph.month:02d}"
        )
        monthly_total = monthly_total_ref.get() or {"total_energy_consumption": 0.0}
        monthly_kwh = float(monthly_total.get("total_energy_consumption", 0.0))

        # Process rule-based logic using user_data for any appliance
        for device_id, appliances in user_data.items():
            for appliance_name, data in appliances.items():
                summary = data
                if not summary:
                    continue
                hourly = summary.get("hourly", {})
                last_hour_kwh = float(hourly.get(last_hour_key, 0))
                total_kwh = float(summary.get("total_kWh", 0))
                avg_power = float(summary.get("avg_power", 0))

                # Historical data (requires additional Firebase fetch or caching)
                historical_kwh = []
                for i in range(1, 8):
                    past_date = (now_ph - timedelta(days=i)).strftime("%Y-%m-%d")
                    past_data_ref = db.reference(
                        f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{past_date}"
                    )
                    past_summary = past_data_ref.get() or {}
                    past_kwh = float(past_summary.get("total_kWh", 0))
                    if past_kwh > 0:
                        historical_kwh.append(past_kwh)
                avg_historical_kwh = (
                    sum(historical_kwh) / len(historical_kwh) if historical_kwh else 0
                )

                # Rule-based peaks for any appliance
                if last_hour_kwh > 0.05 or (
                    avg_historical_kwh and last_hour_kwh > 1.5 * avg_historical_kwh
                ):
                    rule_based_peaks.append(
                        {
                            "appliance": appliance_name,
                            "kWh": round(last_hour_kwh, 2),
                            "hour": last_hour_key,
                        }
                    )

                # Rule-based tips for any appliance with high usage
                if last_hour_kwh > 0.05:
                    rule_based_tips.append(
                        {
                            "priority": "high",
                            "message": f"High usage for {appliance_name} ({last_hour_kwh:.2f} kWh in {last_hour_key}). Reduce usage or turn off when not needed.",
                        }
                    )

                # Budget alerts for any appliance
                if total_kwh > daily_budget * 0.1:
                    budget_alerts.append(
                        {
                            "message": f"{appliance_name} contributed {total_kwh:.2f} kWh today. Reduce usage to stay within your {monthly_budget:.2f} kWh budget."
                        }
                    )

        # Use rule-based peaks and tips only if Gemini failed
        peaks = rule_based_peaks
        tips = rule_based_tips

    return {
        "peaks": peaks,
        "tips": tips,
        "recommendations": recommendations,
        "insights": insights,
        "budget_alerts": budget_alerts,
    }


# @app.get("/asd/{user_id}/{date}")
def fetch_user_data(user_id: str, date: datetime):
    """
    Fetch real-time user energy consumption data for a specific date from Firebase.
    """
    date_str = date.strftime("%Y-%m-%d")
    user_data_ref = db.reference(f"/daily_summary/{user_id}")

    user_data = user_data_ref.get()
    if not user_data:
        raise HTTPException(status_code=404, detail="User data not found.")

    result = {}
    for device_id, device_data in user_data.items():
        for appliance_name, appliance_data in device_data.items():
            if date_str in appliance_data:
                daily_data = appliance_data[date_str]
                result[device_id] = result.get(device_id, {})
                result[device_id][appliance_name] = {
                    "avg_power": daily_data.get("avg_power", "No data available"),
                    "max_power": daily_data.get("max_power", "No data available"),
                    "hourly": daily_data.get("hourly", "No hourly data available"),
                    "total_kWh": daily_data.get("total_kWh", 0),
                    "updated_at": daily_data.get("updated_at", "No data available"),
                }
    return result


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

class PushPayload(BaseModel):
    uid: str        # 👈 which user to notify
    title: str
    body: str
    data: dict | None = None

@app.post("/send-notification/")
async def send_notification(payload: PushPayload):
    # 1. Fetch tokens from Firebase
    tokens_ref = db.reference(f"/tokens/{payload.uid}")
    tokens = tokens_ref.get()

    if not tokens:
        raise HTTPException(status_code=404, detail="No tokens found for this user")

    results = []

    # 2. Loop through all tokens
    for token in tokens:
        message = {
            "to": token,
            "sound": "default",
            "title": payload.title,
            "body": payload.body,
            "data": payload.data or {}
        }

        try:
            response = requests.post(EXPO_PUSH_URL, json=message)
            res_json = response.json()
            results.append({"token": token, "expo_response": res_json})

            # 3. If token is invalid, remove it from Firebase
            if res_json.get("data", {}).get("status") == "error":
                error_type = res_json["data"].get("details", {}).get("error")
                if error_type == "DeviceNotRegistered":
                    tokens_ref.set([t for t in tokens if t != token])
                    print(f"❌ Removed invalid token: {token}")

        except Exception as e:
            results.append({"token": token, "error": str(e)})

    return {"results": results}

# def notify_user(uid: str, title: str, body: str, data: dict | None = None):
#     token = tokens_db.get(uid)
#     if not token:
#         print(f"⚠️ No push token registered for {uid}")
#         return

#     message = {
#         "to": token,
#         "sound": "default",
#         "title": title,
#         "body": body,
#         "data": data or {}
#     }

#     try:
#         response = requests.post(EXPO_PUSH_URL, json=message)
#         print(f"📩 Notification sent to {uid}: {response.json()}")
#     except Exception as e:
#         print(f"❌ Failed to send notification to {uid}: {e}")