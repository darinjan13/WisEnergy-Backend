from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from firebase_admin import db
from datetime import datetime

router = APIRouter()


# ----- SCHEMA -----
class RateRequest(BaseModel):
    city: str
    year: int
    month: str
    rate: float


# ----- ADD / UPDATE -----
@router.post("/rates")
def add_or_update_rate(rate_req: RateRequest):
    print(rate_req)
    """
    Adds or updates an electricity rate for a specific city, year, and month.
    Example path: /city/Mandaue_City/2025/09
    """
    try:
        month = rate_req.month.split("-")[-1]
        city_name = rate_req.city.replace(" ", "_")
        ref = db.reference(f"/city/{city_name}/{rate_req.year}/{month.zfill(2)}")

        payload = {
            "rate": rate_req.rate,
            "set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        ref.set(payload)

        return {
            "status": "success",
            "message": f"Rate for {rate_req.city} ({rate_req.year}-{rate_req.month}) added/updated successfully.",
            "data": payload,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----- GET ALL -----
@router.get("/rates")
def get_all_rates():
    """
    Fetch all city rates in a flattened list for admin table display.
    """
    try:
        city_ref = db.reference("/city").get() or {}
        rates_list = []
        counter = 1

        for city_name, year_data in city_ref.items():
            for year, months in year_data.items():
                for month, data in months.items():
                    rates_list.append(
                        {
                            "id": f"{counter:04}",
                            "city": city_name.replace("_", " "),
                            "year": year,
                            "month": f"{month}",
                            "rate": data.get("rate"),
                            "set_at": data.get("set_at"),
                        }
                    )
                    counter += 1

        # Sort by date (descending)
        rates_list.sort(key=lambda x: x["month"], reverse=True)

        return {"status": "success", "data": rates_list}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----- DELETE -----
@router.delete("/rates/{city}/{year}/{month}")
def delete_rate(city: str, year: int, month: str):
    """
    Deletes a specific city’s rate by year and month.
    Example: DELETE /rates/Mandaue%20City/2025/09
    """
    try:
        city_name = city.replace(" ", "_")
        ref = db.reference(f"/city/{city_name}/{year}/{month.zfill(2)}")
        existing = ref.get()

        if not existing:
            raise HTTPException(status_code=404, detail="Rate not found")

        ref.delete()
        return {
            "status": "success",
            "message": f"Rate for {city} ({year}-{month}) deleted successfully.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
