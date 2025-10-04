from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from ..services.recommendations import (
    generate_recommendation,
    fetch_user_data,
    generate_4hour_recommendation,
)
from ..services.notifications import notify_user, save_notification
from ..utils.firebase import db
from ..utils.timezone import PH_TZ
import json
import re

router = APIRouter()

with open("files/sample_summary.json", "r") as f:
    MOCK_DB = json.load(f)


@router.get("/generate-recommendations/{user_id}/{date}")
async def get_recommendations(user_id: str, date: str):
    try:
        # Parse date
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            target_date = PH_TZ.localize(target_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")

        today = target_date.strftime("%Y-%m-%d")
        hour_key = "23:00"  # testing: always summarize up to end of day

        # Last 4 hours dynamically
        last_4_hours = []
        for j in range(4):
            h_dt = target_date.replace(hour=23, minute=0, second=0) - timedelta(hours=j)
            last_4_hours.append((h_dt.strftime("%Y-%m-%d"), h_dt.strftime("%H:00")))
        last_4_hours.reverse()

        # Collect user data
        user_data = {}
        devices = MOCK_DB.get(user_id, {})
        if not devices:
            raise HTTPException(404, "No usage data found for user.")

        for device_id, appliances in devices.items():
            for appliance_name, daily_data in appliances.items():
                user_data.setdefault(appliance_name, {"hourly": {}})
                hourly_data = daily_data.get(today, {}).get("hourly", {})
                for day_str, h_key in last_4_hours:
                    kwh = hourly_data.get(h_key)
                    if kwh:
                        user_data[appliance_name]["hourly"][h_key] = user_data[
                            appliance_name
                        ]["hourly"].get(h_key, 0.0) + float(kwh)

        # AI recommendations
        ai_data = generate_4hour_recommendation(user_data)
        peaks_str = (
            "\n".join(
                [
                    f"- {p['appliance']}: {p['kWh']} kWh at {p['hour']}"
                    for p in ai_data["peaks"]
                ]
            )
            if ai_data.get("peaks")
            else "No peaks identified."
        )

        insights_str = ai_data.get("insights") or "No insights available."
        recs_str = ai_data.get("recommendations") or "No recommendations available."
        title = "WisEnergy Update ⚡"
        push_body = "Your 4-hour summary is ready. Peaks, insights, and recommendations updated."
        body = (
            f"Your energy summary for the last 4 hours (up to {today} {hour_key}) is updated.\n\n"
            f"Peak Usages:\n{peaks_str}\n\n"
            f"Insights:\n{insights_str}\n\n"
            f"Recommendations:\n{recs_str}"
        )
        print(body)
        # Send push
        notify_user(
            uid=user_id,
            title=title,
            body=push_body,
            data={"screen": "notifications", "date": today, "hour": hour_key},
        )

        # Save full notification
        save_notification(user_id, title, body, ntype="ai_insight")

        return {"user_id": user_id, "date": today, **ai_data}

    except Exception as e:
        raise HTTPException(500, f"Error generating recommendations: {str(e)}")
