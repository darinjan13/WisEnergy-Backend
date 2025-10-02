import json, re
from fastapi import HTTPException
from datetime import datetime, timedelta
from ..config import client_gemini
from ..utils.firebase import db
from ..utils.timezone import PH_TZ


def generate_recommendation(user_data: dict):
    prompt = f"""
        Given the energy consumption data: {json.dumps(user_data)},
        provide a JSON response with:
        1. "peaks": Identify peak time, peak kWh per appliance.
        2. "recommendations": at least 3 practical tips.
        3. "insights": at least 3 concise insights.
    """
    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        cleaned_response = re.sub(r"^```json\n|```$", "", response.text).strip()
        data = json.loads(cleaned_response)

        if "peaks" in data and isinstance(data["peaks"], dict):
            formatted = []
            for appliance, peak in data["peaks"].items():
                formatted.append(
                    {
                        "appliance": appliance,
                        "hour": peak.get("peak_time") or peak.get("hour"),
                        "kWh": peak.get("peak_kWh") or peak.get("kWh"),
                    }
                )
            data["peaks"] = formatted

        return data
    except Exception as e:
        print(f"Error with Gemini: {e}")
        return {"peaks": [], "recommendations": [], "insights": []}


def fetch_user_data(user_id: str, date: datetime):
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
                result.setdefault(device_id, {})[appliance_name] = {
                    "avg_power": daily_data.get("avg_power", "No data"),
                    "max_power": daily_data.get("max_power", "No data"),
                    "hourly": daily_data.get("hourly", {}),
                    "total_kWh": daily_data.get("total_kWh", 0),
                    "updated_at": daily_data.get("updated_at", "No data"),
                }
    return result
