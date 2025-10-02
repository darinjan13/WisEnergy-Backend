from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from ..utils.firebase import db
from ..services.predictions import (
    appliance_daily_prediction,
    appliance_weekly_prediction,
)

router = APIRouter()


@router.get("/{user_id}/{device_id}/{appliance_name}")
def predict_and_return_history(user_id: str, device_id: str, appliance_name: str):
    try:
        today = datetime.now().date()

        # ---------- DAILY ----------
        daily_ref = db.reference(
            f"/predictions/{user_id}/{device_id}/{appliance_name}/daily"
        )
        all_daily = daily_ref.get() or {}

        # find last predicted date
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

        # fill gaps
        last_week = flat_weeks[-1] if flat_weeks else None
        target_week = (now.year, now.month, int(current_week))

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
