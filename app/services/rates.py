import requests, json, time
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil.relativedelta import relativedelta
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


GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]


def gemini_generate(contents, attempts_per_model=2):
    last_error = None
    for model in GEMINI_MODELS:
        for attempt in range(attempts_per_model):
            try:
                result = client_gemini.models.generate_content(
                    model=model, contents=contents
                )
                print(f"[RATES] Gemini ok via {model}")
                return result, model
            except Exception as e:
                last_error = e
                message = str(e).lower()
                transient = any(
                    token in message
                    for token in (
                        "503",
                        "unavailable",
                        "429",
                        "overloaded",
                        "deadline",
                        "timeout",
                    )
                )
                print(
                    f"[RATES] Gemini {model} attempt {attempt + 1} failed: "
                    f"{type(e).__name__}: {str(e)[:160]}"
                )
                if not transient:
                    break
                time.sleep(1.5 * (attempt + 1))
    raise last_error if last_error else RuntimeError("no Gemini model succeeded")


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


def find_latest_meco_image_url():
    today = datetime.now()
    for i in range(12):
        d = today - relativedelta(months=i)
        url = build_meco_url(d)
        html = try_fetch_html(url)
        if not html:
            continue
        img_url = extract_image_url(html)
        if img_url:
            return d.year, d.month, img_url
    return None, None, None


# -----------------------------
# MECO OCR
# -----------------------------
def extract_meco_rate(image_bytes):

    prompt = """
From this MECO residential rate table, return ONLY the numeric value on the
'Average Rate After VAT' row (the total consumers actually pay, e.g. 15.9806).
Do NOT return the Generation, Distribution, Lifeline, Government, VAT, or
'Before VAT' rows. No words. No labels. Just the number.
"""

    contents = [
        {
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
            ],
        }
    ]

    result, model = gemini_generate(contents)
    print(f"[RATES] MECO OCR via {model}")

    raw = (result.text or "").strip()
    try:
        rate = float(raw)
    except Exception:
        print(f"[RATES] MECO OCR unparseable: {raw!r}")
        return None
    if not 5.0 <= rate <= 25.0:
        print(f"[RATES] MECO OCR out of range ({rate}), raw={raw!r}")
        return None
    return rate


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

    result, model = gemini_generate([prompt])
    print(f"[RATES] VECO lookup via {model}")

    raw = (result.text or "").strip()

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
def rate_exists(city, year, month):
    key = f"{int(month):02d}"
    return db.reference(f"city/{city}/{int(year)}/{key}").get() is not None


def scheduled_rates_update():
    print("[RATES] Starting update...")
    result = {"meco": None, "veco": None, "skipped": False}

    now = datetime.now()
    if rate_exists("Lapu-Lapu_City", now.year, now.month) and rate_exists(
        "Mandaue_City", now.year, now.month
    ):
        print(f"[RATES] {now.year}/{now.month:02d} already stored for both cities - nothing to do")
        result["skipped"] = True
        return result

    meco_year = meco_month = meco_img_url = None
    try:
        meco_year, meco_month, meco_img_url = find_latest_meco_image_url()
    except Exception as e:
        print(f"[RATES] MECO page lookup error: {e}")

    if meco_year is None:
        print("[RATES] No MECO page found in the last 12 months")
    elif rate_exists("Lapu-Lapu_City", meco_year, meco_month):
        print(f"[RATES] MECO {meco_year}/{meco_month:02d} already stored - skipping lookup")
    else:
        try:
            print(f"[RATES] Fetching MECO image for {meco_year}/{meco_month:02d}")
            meco_img = download_image_bytes(meco_img_url)
            meco_rate = extract_meco_rate(meco_img)
            print(f"[RATES] MECO rate: {meco_rate}")
            if meco_rate:
                save_rate_if_not_exists(
                    "Lapu-Lapu_City", meco_year, f"{meco_month:02d}", meco_rate
                )
                result["meco"] = meco_rate
        except Exception as e:
            print(f"[RATES] MECO error: {e}")

    veco_year = meco_year if meco_year else now.year
    veco_month = meco_month if meco_month else now.month

    if rate_exists("Mandaue_City", veco_year, veco_month):
        print(f"[RATES] VECO {veco_year}/{veco_month:02d} already stored - skipping lookup")
    else:
        try:
            print("[RATES] Fetching VECO rate...")
            veco_data = extract_veco_rate()
            print(f"[RATES] VECO data: {veco_data}")
            veco_rate = veco_data.get("total_average_rate")
            if veco_rate is None:
                print("[RATES] VECO rate missing")
            elif not 5.0 <= veco_rate <= 25.0:
                print(f"[RATES] VECO rate out of range ({veco_rate}) - not saved")
            else:
                save_rate_if_not_exists(
                    "Mandaue_City", veco_year, f"{veco_month:02d}", veco_rate
                )
                result["veco"] = veco_rate
        except Exception as e:
            print(f"[RATES] VECO error: {e}")

    print("[RATES] Done:", result)
    return result
