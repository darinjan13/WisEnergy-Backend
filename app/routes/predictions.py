from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from ..utils.firebase import db
from ..services.predictions import (
    appliance_daily_prediction,
    appliance_weekly_prediction,
    total_daily_prediction,
    total_weekly_prediction,
)

router = APIRouter()


@router.get("/predict/{user_id}/{device_id}/{appliance_name}")
def predict_and_return_history(user_id: str, device_id: str, appliance_name: str):
    try:
        # ---------- DAILY ----------
        daily_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/daily"
        )
        all_daily = daily_ref.get() or {}
        last5_daily = {d: all_daily[d] for d in sorted(all_daily.keys())[-5:]}

        # ---------- MONTHLY (current year, all months) ----------
        now_month = datetime.now()
        current_year_month = now_month.year

        monthly_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/monthly/{current_year_month}"
        )
        year_data = monthly_ref.get() or {}

        monthly_list = []
        for mm in range(1, 12 + 1):
            key = f"{mm:02d}"
            payload = year_data.get(key) or {}
            monthly_list.append(
                {
                    "year": current_year_month,
                    "month": key,
                    "predicted_kWh": payload.get("predicted_kWh", 0),
                    "timestamp": payload.get("timestamp", ""),
                }
            )

        # ---------- WEEKLY ----------
        weekly_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/weekly"
        )
        all_weekly = weekly_ref.get() or {}

        if not all_weekly:
            return {"daily": last5_daily, "weekly": [], "monthly": monthly_list}

        flat_weeks = []
        for yy, months in all_weekly.items():
            for mm, weeks in (months or {}).items():
                for ww, payload in (weeks or {}).items():
                    flat_weeks.append((int(yy), int(mm), int(ww), payload))
        flat_weeks.sort(key=lambda x: (x[0], x[1], x[2]))

        if not flat_weeks:
            return {"daily": last5_daily, "weekly": [], "monthly": monthly_list}

        # 🔹 Determine current & previous month
        now = datetime.now()
        current_year, current_month = now.year, now.month
        prev_month = current_month - 1 or 12
        prev_year = current_year if current_month > 1 else current_year - 1

        # 🔹 Separate current vs previous month data
        this_month = [
            w for w in flat_weeks if w[0] == current_year and w[1] == current_month
        ]
        prev_month_data = [
            w for w in flat_weeks if w[0] == prev_year and w[1] == prev_month
        ]

        # 🔹 Choose which to include
        if len(this_month) >= 2:
            selected = this_month
        else:
            selected = (prev_month_data[-1:] if prev_month_data else []) + this_month

        last_weeks = [
            {"year": yy, "month": f"{mm:02d}", "week": f"{ww:02d}", "data": payload}
            for yy, mm, ww, payload in selected
        ]

        return {"daily": last5_daily, "weekly": last_weeks, "monthly": monthly_list}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predict/totals/{user_id}")
def predict_total_and_return_history(user_id: str):
    """Retrieve recent daily and weekly total consumption predictions for a user."""
    try:
        # ---------- DAILY TOTAL ----------
        daily_ref = db.reference(f"/predictions/{user_id}/total_consumption/daily")
        all_daily = daily_ref.get() or {}
        last7_daily = {d: all_daily[d] for d in sorted(all_daily.keys())[-7:]}

        # ---------- MONTHLY TOTAL (current year, all months) ----------
        now_month = datetime.now()
        current_year_month = now_month.year

        monthly_ref = db.reference(
            f"/predictions/{user_id}/total_consumption/monthly/{current_year_month}"
        )
        year_data = monthly_ref.get() or {}

        monthly_list = []
        for mm in range(1, 12 + 1):
            key = f"{mm:02d}"
            payload = year_data.get(key) or {}
            monthly_list.append(
                {
                    "year": current_year_month,
                    "month": key,
                    "predicted_kWh": payload.get("predicted_kWh", 0),
                    "timestamp": payload.get("timestamp", ""),
                }
            )

        # ---------- WEEKLY TOTAL ----------
        weekly_ref = db.reference(f"/predictions/{user_id}/total_consumption/weekly")
        all_weekly = weekly_ref.get() or {}

        flat_weeks = []
        for yy, months in all_weekly.items():
            for mm, weeks in (months or {}).items():
                for ww, payload in (weeks or {}).items():
                    flat_weeks.append((int(yy), int(mm), int(ww), payload))
        flat_weeks.sort(key=lambda x: (x[0], x[1], x[2]))

        if not flat_weeks:
            return {
                "daily": last7_daily,
                "weekly": [],
                "monthly": monthly_list,
            }

        # 🔹 Current and previous month check
        now = datetime.now()
        current_year, current_month = now.year, now.month
        prev_month = current_month - 1 or 12
        prev_year = current_year if current_month > 1 else current_year - 1

        this_month = [
            w for w in flat_weeks if w[0] == current_year and w[1] == current_month
        ]
        prev_month_data = [
            w for w in flat_weeks if w[0] == prev_year and w[1] == prev_month
        ]

        # 🔹 Logic: 2+ weeks → use only this month. else → include 1 previous
        if len(this_month) >= 2:
            selected = this_month
        else:
            selected = (prev_month_data[-1:] if prev_month_data else []) + this_month

        weekly_predictions = [
            {"year": yy, "month": f"{mm:02d}", "week": f"{ww:02d}", "data": payload}
            for yy, mm, ww, payload in selected
        ]

        return {
            "daily": last7_daily,
            "weekly": weekly_predictions,
            "monthly": monthly_list,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
