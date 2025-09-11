import os
import smtplib
import random
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr
from fastapi import FastAPI, Request, Response, HTTPException
from firebase_admin import credentials, db, initialize_app, firestore
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
                ).set(
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


scheduler = BackgroundScheduler()
scheduler.add_job(summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ)
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
    predicted_kwh = round(prediction['yhat'], 2)
    
    print(f"Predicted kwh for tomorrow: {predicted_kwh}")
    return predicted_kwh

def generate_otp_code():
    return f"{random.randint(100000, 999999)}"

def send_otp_email(to_email: str, otp: str):
    subject = "Your WisEnergy Password Reset Code"
    body = f"Your reset code: {otp}\nIt will expire in 5 minutes"
    
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = EMAIL_ADDRESS
    message["To"] = to_email
    
    try:
        with smtplib.SMTP("smtp.gemail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(message)
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

@app.get("/generate-otp")
def generate_otp(req: OTPRequest):
    email_id = req.email.replace(".", "_")
    otp = generate_otp_code()
    expires = datetime.utcnow() + timedelta(minutes=5)
    fs.collection("otp-verification").document(email_id).set({
        "otp": otp,
        "expires_at": expires.isoformat,
        "verified": False
    })
    
    send_otp_email(req.email, otp)
    return {"message": f"OTP sent to {req.email}"}

@app.get("/predict/{user_id}/{device_id}/{appliance_name}")
def predict_daily_appliance_kwh(user_id: str, device_id: str, appliance_name: str):
    try:
        result = appliance_daily_prediction(user_id, device_id, appliance_name)
        if result is None:
            raise HTTPException(status_code=400, detail="Not enough data for prediction.")
        return round(result, 2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# @app.get("/generate-summaries")
# def generate_summaries():
#     print("📊 Backfill: replaying summary_aggregation() from 2025-06-01 to today…")

#     interval_seconds = 5

#     start_date = PH_TZ.localize(datetime(2025, 8, 1)).replace(
#         hour=0, minute=0, second=0, microsecond=0
#     )
#     end_date = datetime.now(PH_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

#     usage_root = db.reference("/usage").get()
#     if not usage_root:
#         return {"error": "No /usage data found."}

#     run_dt = start_date
#     while run_dt <= end_date:
#         now_ph = run_dt
#         summaries_at = now_ph.replace(
#             hour=0, minute=5, second=0, microsecond=0
#         ).strftime("%Y-%m-%d %H:%M:%S")
#         totals_at = now_ph.replace(hour=0, minute=10, second=0, microsecond=0).strftime(
#             "%Y-%m-%d %H:%M:%S"
#         )

#         # Your main computes daily for yesterday
#         target_dt = now_ph - timedelta(days=1)
#         target_date = target_dt.strftime("%Y-%m-%d")

#         is_monday = now_ph.weekday() == 0
#         is_first_of_month = now_ph.day == 1
#         y = str((now_ph - timedelta(days=1)).year)
#         m = f"{(now_ph - timedelta(days=1)).month:02d}"
#         w = f"{(((now_ph - timedelta(days=1)).day - 1) // 7) + 1:02d}"  # '01'..'05'

#         print(
#             f"📆 Run day: {now_ph.date()} | Daily target: {target_date} | "
#             f"{'Mon ' if is_monday else ''}{'1st-of-month' if is_first_of_month else ''}"
#         )

#         # ------------------ DAILY ------------------
#         for user_id, devices in (usage_root or {}).items():
#             user_kwh = 0.0

#             for device_id, appliances in (devices or {}).items():
#                 for appliance_name, dates in (appliances or {}).items():
#                     day_data = (dates or {}).get(target_date)
#                     if not day_data:
#                         continue

#                     powers = [float(r.get("power", 0)) for r in day_data.values()]
#                     if not powers:
#                         continue

#                     total_kwh = sum(
#                         (p / 1000.0) * (interval_seconds / 3600.0) for p in powers
#                     )
#                     avg_power = sum(powers) / len(powers)
#                     max_power = max(powers)

#                     db.reference(
#                         f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{target_date}"
#                     ).set(
#                         {
#                             "total_kWh": round(total_kwh, 6),
#                             "avg_power": round(avg_power, 2),
#                             "max_power": round(max_power, 2),
#                             "updated_at": summaries_at,
#                         }
#                     )
#                     user_kwh += total_kwh

#             db.reference(f"/daily_total_consumption/{user_id}/{target_date}").set(
#                 {
#                     "total_energy_consumption": round(user_kwh, 2),
#                     "updated_at": totals_at,
#                 }
#             )
#             monthly_total = (
#                 db.reference(
#                     f"/monthly_total_consumption/{user_id}/{y}/{m}/total_energy_consumption"
#                 ).get()
#                 or 0
#             )
#             print(f"Monthly Total Consumption: {monthly_total + user_kwh}")
#             db.reference(f"/monthly_total_consumption/{user_id}/{y}/{m}").update(
#                 {
#                     "total_energy_consumption": round(monthly_total + user_kwh, 2),
#                     "updated_at": totals_at,
#                 }
#             )

#             # ------------------ WEEKLY (previous Mon–Sun; EXCLUDES current Monday) ------------------
#         # ------------------ WEEKLY (previous Mon–Sun; Monday-owned bucket) ------------------
#         if is_monday:
#             prev_week_end = now_ph - timedelta(days=1)  # Sunday (yesterday)
#             prev_week_start = prev_week_end - timedelta(days=6)  # Monday of last week

#             # bucket from the Monday
#             y = str(prev_week_start.year)
#             m = f"{prev_week_start.month:02d}"
#             w = f"{((prev_week_start.day - 1) // 7) + 1:02d}"  # '01'..'05'

#             days = [
#                 (prev_week_start + timedelta(days=i)).strftime("%Y-%m-%d")
#                 for i in range(7)
#             ]

#             weekly_user_totals = {}

#             for user_id, devices in (usage_root or {}).items():
#                 user_week_total = 0.0

#                 for device_id, appliances in (devices or {}).items():
#                     for appliance_name in (appliances or {}).keys():
#                         total_kwh_week = 0.0
#                         for d in days:
#                             summary = db.reference(
#                                 f"/daily_summary/{user_id}/{device_id}/{appliance_name}/{d}"
#                             ).get()
#                             if summary:
#                                 total_kwh_week += float(summary.get("total_kWh", 0.0))

#                         # /weekly_summary/{user}/{device}/{appliance}/{YYYY}/{MM}/{WW}
#                         db.reference(
#                             f"/weekly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}/{w}"
#                         ).set(
#                             {
#                                 "total_kWh": round(total_kwh_week, 6),
#                                 "start_date": prev_week_start.strftime("%Y-%m-%d"),
#                                 "end_date": prev_week_end.strftime("%Y-%m-%d"),
#                                 "updated_at": summaries_at,
#                             }
#                         )

#                         user_week_total += total_kwh_week

#                 weekly_user_totals[user_id] = (
#                     weekly_user_totals.get(user_id, 0.0) + user_week_total
#                 )

#             # /weekly_total_consumption/{user}/{YYYY}/{MM}/{WW}
#             for user_id, tot in weekly_user_totals.items():
#                 db.reference(f"/weekly_total_consumption/{user_id}/{y}/{m}/{w}").set(
#                     {"total_energy_consumption": round(tot, 2), "updated_at": totals_at}
#                 )

#         # # ------------------ MONTHLY (previous month; reads from daily_summary) ------------------
#         # if is_first_of_month:
#         #     prev_month_dt = now_ph - timedelta(days=1)  # last day of previous month
#         #     y, m = str(prev_month_dt.year), f"{prev_month_dt.month:02d}"
#         #     month_prefix = f"{y}-{m}"

#         #     monthly_user_totals = {}

#         #     for user_id, devices in (usage_root or {}).items():
#         #         user_month_total = 0.0

#         #         for device_id, appliances in (devices or {}).items():
#         #             for appliance_name in (appliances or {}).keys():
#         #                 total_kwh_month = 0.0

#         #                 daily_branch = (
#         #                     db.reference(
#         #                         f"/daily_summary/{user_id}/{device_id}/{appliance_name}"
#         #                     ).get()
#         #                     or {}
#         #                 )
#         #                 for d, summary in daily_branch.items():
#         #                     if isinstance(d, str) and d.startswith(month_prefix):
#         #                         total_kwh_month += float(summary.get("total_kWh", 0.0))

#         #                 # /monthly_summary/{user}/{device}/{appliance}/{YYYY}/{MM}
#         #                 db.reference(
#         #                     f"/monthly_summary/{user_id}/{device_id}/{appliance_name}/{y}/{m}"
#         #                 ).set(
#         #                     {
#         #                         "total_kWh": round(total_kwh_month, 6),
#         #                         "updated_at": summaries_at,
#         #                     }
#         #                 )

#         #                 user_month_total += total_kwh_month

#         #         monthly_user_totals[user_id] = user_month_total

#         #     # /monthly_total_consumption/{user}/{YYYY}/{MM}
#         #     for user_id, tot in monthly_user_totals.items():
#         #         db.reference(f"/monthly_total_consumption/{user_id}/{y}/{m}").set(
#         #             {"total_energy_consumption": round(tot, 2), "updated_at": totals_at}
#         #         )

#         run_dt += timedelta(days=1)

#     print("✅ Backfill done: daily + (prev week) weekly + (prev month) monthly.")
#     return {"message": "Backfill complete using summary_aggregation() logic."}
