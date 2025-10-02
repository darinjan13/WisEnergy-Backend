import pandas as pd
from prophet import Prophet
from datetime import datetime
from ..utils.timezone import PH_TZ
from ..utils.firebase import db


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
    return round(prediction["yhat"], 2)


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

    future = model.make_future_dataframe(periods=1, freq="W-MON")
    forecast = model.predict(future)
    prediction = forecast.iloc[-1]
    return round(prediction["yhat"], 2)
