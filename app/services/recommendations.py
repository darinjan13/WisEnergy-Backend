import json, re
from fastapi import HTTPException
from datetime import datetime
from ..config import client_gemini
from ..utils.firebase import db
from statistics import mean


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
        1. "peaks": Identify today's peak usage per appliance using keys as appliance names. Include "peak_time" and "peak_kWh". Ignore appliances with no data.
        2. "recommendations": Provide at least 3 short recommendations (2-3 sentences each). Message only, no title.
        3. "insights": Provide at least 3 insights based on usage data (1-2 sentences each). Message only, no title.
        Only JSON output.
    """

    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        cleaned_response = re.sub(r"^```json\n|```$", "", response.text).strip()

        data = json.loads(cleaned_response)
        peaks = data.get("peaks", {})

        # Prevent crashes by validating peak structure
        formatted = []
        if isinstance(peaks, dict):
            for appliance, peak in peaks.items():
                # normalize peak to dict
                if isinstance(peak, dict):
                    hour = peak.get("peak_time") or peak.get("hour")
                    kwh = peak.get("peak_kWh") or peak.get("kWh")
                else:
                    # if peak is number or anything else, fall back safely
                    hour = None
                    kwh = float(peak) if isinstance(peak, (int, float)) else None

                formatted.append(
                    {
                        "appliance": appliance,
                        "hour": hour,
                        "kWh": kwh,
                    }
                )
        else:
            peaks = []

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


def detect_high_usage_peaks(user_data: dict):
    """
    Detects high-usage peaks per appliance in the last 4-hour window.

    A peak is defined when the max kWh is >= 2× the average (excluding the peak itself)
    and above a 0.1 kWh threshold.
    Returns a list of dicts: [{"appliance": str, "hour": str, "kWh": float}].
    """
    peaks = []
    THRESHOLD_MULTIPLIER = 2.0
    MIN_THRESHOLD_KWH = 0.1

    for app, details in user_data.items():
        hourly_items = details.get("hourly", {})
        hourly_kwh = list(hourly_items.values())
        if len(hourly_kwh) < 2:
            continue

        max_kwh = max(hourly_kwh)
        max_hours = [hour for hour, kwh in hourly_items.items() if kwh == max_kwh]

        non_max_kwh = hourly_kwh.copy()
        if max_kwh in non_max_kwh:
            non_max_kwh.remove(max_kwh)
        base = mean(non_max_kwh) if non_max_kwh else 0

        if (
            base > 0
            and max_kwh >= base * THRESHOLD_MULTIPLIER
            and max_kwh >= MIN_THRESHOLD_KWH
        ):
            for hour in max_hours:
                peaks.append({"appliance": app, "hour": hour, "kWh": max_kwh})
                print(
                    f"📈 Peak detected for {app} — {max_kwh:.2f} kWh at {hour} "
                    f"(baseline ≈ {base:.2f}, threshold × {THRESHOLD_MULTIPLIER})"
                )

    return peaks
