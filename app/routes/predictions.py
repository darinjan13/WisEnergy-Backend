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

        # ---------- WEEKLY ----------
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

        last7_weekly = [
            {"year": yy, "month": f"{mm:02d}", "week": f"{ww:02d}", "data": payload}
            for yy, mm, ww, payload in flat_weeks[-7:]
        ]

        return {"daily": last5_daily, "weekly": last7_weekly}

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

        # ---------- WEEKLY TOTAL ----------
        weekly_ref = db.reference(f"/predictions/{user_id}/total_consumption/weekly")
        all_weekly = weekly_ref.get() or {}
        flat_weeks = []
        for yy, months in (all_weekly or {}).items():
            for mm, weeks in (months or {}).items():
                for ww, payload in (weeks or {}).items():
                    flat_weeks.append((int(yy), int(mm), int(ww), payload))
        flat_weeks.sort(key=lambda x: (x[0], x[1], x[2]))
        last6_weekly = [
            {"year": yy, "month": f"{mm:02d}", "week": f"{ww:02d}", "data": payload}
            for yy, mm, ww, payload in flat_weeks[-6:]
        ]

        return {"daily": last7_daily, "weekly": last6_weekly}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
