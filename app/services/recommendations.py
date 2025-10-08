import json, re
from fastapi import HTTPException
from datetime import datetime
from ..config import client_gemini
from ..utils.firebase import db


def generate_4hour_recommendation(user_data: dict):
    prompt = f"""
Given the energy consumption data for the last 4 hours in JSON format:
{json.dumps(user_data, indent=2)},

Analyze the data to provide a JSON response with:
1. "recommendations": A list containing exactly one concise, practical recommendation to reduce energy usage. Focus on specific actions based on observed usage patterns (e.g., high usage in certain hours or appliances). Avoid generic advice like "save energy." Do not mention products or brands.
2. "insights": A list containing exactly one concise analysis of the usage data, highlighting a specific pattern or trend (e.g., peak hours, high-usage appliances).

**Constraints**:
- Each recommendation and insight must be a single sentence, max 25 words.
- Base outputs on the provided 4-hour data (appliance names and hourly kWh).
- If data is empty or insufficient, return a default recommendation ("Turn off unused appliances during low activity hours.") and insight ("Insufficient data to identify usage patterns.").
- Ensure JSON keys are "recommendations" and "insights", with values as lists of strings.
- Do not include "peaks" or peak detection; focus only on recommendations and insights.

**Example Input**:
```json
{{
  "Air Conditioner": {{"hourly": {{"20:00": 2.8, "21:00": 2.7, "22:00": 2.9, "23:00": 10.0}}}},
  "Fan": {{"hourly": {{"20:00": 0.12, "21:00": 0.13, "22:00": 0.14, "23:00": 0.15}}}}
}}
```

**Example Output**:
```json
{{
  "recommendations": ["Shift air conditioner usage to off-peak hours to reduce evening energy spikes."],
  "insights": ["Air conditioner usage peaks significantly at 23:00, indicating high evening demand."]
}}
```

Return the response as a valid JSON string, wrapped in ```json\n...\n```.
"""
    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        cleaned_response = re.sub(r"^```json\n|```$", "", response.text).strip()
        print(f"Gemini response: {cleaned_response}")
        data = json.loads(cleaned_response)

        # Ensure recommendations and insights are lists
        recommendations = data.get(
            "recommendations", ["Turn off unused appliances during low activity hours."]
        )
        insights = data.get(
            "insights", ["Insufficient data to identify usage patterns."]
        )
        if isinstance(recommendations, str):
            recommendations = [recommendations]
        if isinstance(insights, str):
            insights = [insights]

        return {
            "recommendations": recommendations[:1],  # Ensure exactly one
            "insights": insights[:1],
        }
    except Exception as e:
        print(f"Error with Gemini: {e}")
        return {
            "recommendations": [
                "Turn off unused appliances during low activity hours."
            ],
            "insights": ["Insufficient data to identify usage patterns."],
        }


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


from statistics import mean


def detect_high_usage_peaks(user_data: dict):
    """
    Detect high usage peaks in the 4-hour window for each appliance using only user_data.

    Args:
        user_data (dict): Dictionary with appliance names as keys and hourly kWh data.

    Returns:
        list: Peaks [{"appliance": str, "hour": str, "kWh": float}] where max kWh exceeds
              twice the mean of non-max hours.
    """
    peaks = []

    for app, details in user_data.items():
        hourly_items = details.get("hourly", {})
        hourly_kwh = list(hourly_items.values())
        if len(hourly_kwh) < 2:  # Need at least 2 hours for meaningful baseline
            continue

        # Find max kWh and its hour
        max_kwh = max(hourly_kwh)
        max_hour = next(hour for hour, kwh in hourly_items.items() if kwh == max_kwh)

        # Baseline: mean excluding the max kWh (to detect isolated spikes)
        non_max_kwh = [kwh for kwh in hourly_kwh if kwh != max_kwh]
        base = mean(non_max_kwh) if non_max_kwh else 0

        # Flag as high usage if max >= 2 * baseline and above min threshold
        if base > 0 and max_kwh >= base * 2.0 and max_kwh >= 0.1:
            peaks.append({"appliance": app, "hour": max_hour, "kWh": max_kwh})
            print(
                f"📈 Detected peak for {app}: {max_kwh:.2f} kWh at {max_hour} (baseline avg excluding peak ≈ {base:.2f})"
            )

    return peaks
