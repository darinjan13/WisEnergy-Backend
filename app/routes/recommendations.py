from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from ..services.recommendations import generate_recommendation, fetch_user_data
from ..utils.firebase import db
from ..utils.timezone import PH_TZ

router = APIRouter()


@router.get("/generate-recommendations/{user_id}/{date}")
async def get_recommendations(user_id: str, date: datetime):
    user_data = fetch_user_data(user_id, date)
    ai_recommendations = generate_recommendation(user_data)

    now_ph = datetime.now(PH_TZ)
    today = now_ph.strftime("%Y-%m-%d")

    budget_ref = db.reference(
        f"/user_monthly_budget/{user_id}/{now_ph.year}/{now_ph.month:02d}/budget_kwh"
    )
    monthly_budget = budget_ref.get() or 0.0
    daily_budget = monthly_budget / 30 if monthly_budget else float("inf")

    peaks = ai_recommendations.get("peaks", [])
    tips = [
        {"priority": "low", "message": rec}
        for rec in ai_recommendations.get("recommendations", [])
    ]
    insights = ai_recommendations.get("insights", [])
    budget_alerts = []

    return {
        "peaks": peaks,
        "tips": tips,
        "recommendations": ai_recommendations.get("recommendations", []),
        "insights": insights,
        "budget_alerts": budget_alerts,
    }
