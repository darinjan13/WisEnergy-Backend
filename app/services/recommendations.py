import json, re
from fastapi import HTTPException
from datetime import datetime
from ..config import client_gemini
from ..utils.firebase import db


def generate_4hour_recommendation(user_data: dict):
    prompt = f"""
        Given the energy consumption data for the last 4 hours: {json.dumps(user_data)},
        provide a JSON response with:
        1. "peaks": Identify the peak time and peak kWh for each appliance (ignore appliances with no data in this period). Use appliance names as keys and return a single peak per appliance in the format {{"hour": "HH:00", "kWh": float}}. Do not use device IDs.
        2. "recommendations": Analyze the usage and provide exactly 1 concise recommendation to reduce energy usage (message only, no title, avoid product mentions).
        3. "insights": Provide exactly 1 concise analysis based on the usage data (message only, no title).
        Ensure recommendations are practical and avoid mentioning products.
    """
    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        cleaned_response = re.sub(r"^```json\n|```$", "", response.text).strip()
        print(cleaned_response)
        data = json.loads(cleaned_response)

        if "peaks" in data and isinstance(data["peaks"], dict):
            formatted = []
            for appliance, peak in data["peaks"].items():
                formatted.append(
                    {
                        "appliance": appliance,
                        "hour": peak.get("peak_time")
                        or peak.get("hour")
                        or peak.get("peak_hour"),
                        "kWh": peak.get("peak_kWh")
                        or peak.get("peak_kwh")
                        or peak.get("kWh")
                        or peak.get("kwh"),
                    }
                )
            data["peaks"] = formatted
        print(data)
        return data
    except Exception as e:
        print(f"Error with Gemini: {e}")
        return {"peaks": [], "recommendations": [], "insights": []}


def generate_recommendation(user_data: dict):
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
            model="gemini-2.5-flash",
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
