from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from .utils.timezone import PH_TZ
from .services.summaries import (
    hourly_summary_update,
)
from .services.predictions import scheduled_prediction_update

# from .services.users import check_scheduled_deletions
from .routes import (
    users,
    devices,
    reviews,
    feedback,
    recommendations,
    auth,
    notifications,
    predictions,
    rates,
    paymongo,
)

app = FastAPI()

# CORS
origins = ["http://localhost:5173", "https://wisenergy.site"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(reviews.router)
app.include_router(feedback.router)
app.include_router(auth.router)
app.include_router(recommendations.router)
app.include_router(notifications.router)
app.include_router(predictions.router)
app.include_router(rates.router)
app.include_router(paymongo.router)


@app.get("/")
def root():
    return {"message": "WisEnergy API running"}


@app.api_route("/ping", methods=["GET", "HEAD"])
def ping(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return {"message": "pong"}


# Scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    scheduled_prediction_update, "cron", hour=0, minute=20, timezone=PH_TZ
)
scheduler.add_job(hourly_summary_update, "cron", minute=0, timezone=PH_TZ)
scheduler.start()
