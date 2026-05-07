import requests, json
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil.relativedelta import relativedelta
from google.genai import types
from ..config import client_gemini
from ..utils.firebase import db

MONTH_SLUGS = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sept",
    10: "oct",
    11: "nov",
    12: "dec",
}


# -----------------------------
# MECO URL FINDER
# -----------------------------
def build_meco_url(date_obj):
    slug = MONTH_SLUGS[date_obj.month]
    return f"https://mecomactan.com/average-{slug}-{date_obj.year}-rate/"


def try_fetch_html(url):
    try:
        res = requests.get(url, timeout=10)
        return res.text if res.status_code == 200 else None
    except:
        return None


def extract_image_url(html):
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one("div.fusion-text img") or soup.find("img")
    if not img:
        return None
    src = img.get("src")
    return src if src.startswith("http") else "https://mecomactan.com" + src


def download_image_bytes(url):
    return requests.get(url, timeout=10).content


def get_latest_meco_image_bytes():
    today = datetime.now()
    for i in range(12):
        d = today - relativedelta(months=i)
        url = build_meco_url(d)
        html = try_fetch_html(url)
        if not html:
            continue
        img_url = extract_image_url(html)
        if img_url:
            return download_image_bytes(img_url), d.year, d.month
    return None, None, None


# -----------------------------
# MECO OCR
# -----------------------------
def extract_meco_rate(image_bytes):

    prompt = """
Extract ONLY the numeric Total Average Rate from the MECO rate image.
Example output: 11.0864
No words. No labels.
"""

    result = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
                ],
            }
        ],
    )

    try:
        return float(result.text.strip())
    except:
        return None


# -----------------------------
# VECO LOOKUP (Stable)
# -----------------------------
def extract_veco_rate():

    prompt = """
What is the latest VECO (Visayan Electric Company) Cebu residential electricity rate per kWh?
Return ONLY JSON like this:
{ "total_average_rate": 12.34 }
Do NOT include code blocks or explanations.
"""

    # call Gemini without search tool - uses trained knowledge
    result = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
    )

    raw = result.text.strip()

    # --- CLEANING PHASE ---
    # remove ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()

    # remove trailing/leading whitespace
    raw = raw.strip()

    # ensure it LOOKS like JSON
    if not raw.startswith("{"):
        # fallback: model hallucinated text; extract number manually
        import re

        match = re.search(r"(\d+\.\d+)", raw)
        if match:
            return {"total_average_rate": float(match.group(1))}
        else:
            return {"total_average_rate": None, "raw_output": raw}

    # --- JSON PARSING ---
    try:
        data = json.loads(raw)
    except:
        # last fallback attempt: extract numbers
        import re

        match = re.search(r"(\d+\.\d+)", raw)
        if match:
            return {"total_average_rate": float(match.group(1))}
        return {"total_average_rate": None, "raw_output": raw}

    # normalize key names
    for key in list(data.keys()):
        if key.lower().replace(" ", "_") == "total_average_rate":
            data["total_average_rate"] = data.pop(key)

    # if still missing, fallback
    if "total_average_rate" not in data:
        import re

        match = re.search(r"(\d+\.\d+)", raw)
        if match:
            data["total_average_rate"] = float(match.group(1))
        else:
            data["total_average_rate"] = None

    return data


def save_rate_if_not_exists(city, year, month, rate):
    ref = db.reference(f"city/{city}/{year}/{month}")

    existing = ref.get()
    if existing is not None:
        print(f"[RATES] {city} {year}/{month} already exists. Skipping.")
        return False

    ref.set({"rate": rate, "set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    print(f"[RATES] Saved {city} {year}/{month}: {rate}")
    return True


# -----------------------------
# MAIN
# -----------------------------
def scheduled_rates_update():
    meco_img, meco_year, meco_month = get_latest_meco_image_bytes()
    meco_rate = extract_meco_rate(meco_img)
    veco_data = extract_veco_rate()
    veco_rate = veco_data.get("total_average_rate")

    now = datetime.now()
    year = meco_year
    month = f"{meco_month:02d}"

    # Save MECO → Lapu-Lapu City
    save_rate_if_not_exists("Lapu-Lapu_City", year, month, meco_rate)

    # Save VECO → Mandaue City
    save_rate_if_not_exists("Mandaue_City", year, month, veco_rate)

    print("[RATES] Done:", {"meco": meco_rate, "veco": veco_rate})

    return {"meco": meco_rate, "veco": veco_rate}
