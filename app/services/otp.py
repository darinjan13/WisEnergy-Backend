from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from ..utils.timezone import PH_TZ
from .summaries import (
    hourly_summary_update,
    weekly_summary_aggregation,
    total_energy_consumption,
)
from ..services.predictions import scheduled_prediction_update
from ..routes import (
    users,
    devices,
    reviews,
    feedback,
    auth,
    recommendations,
    notifications,
)

app = FastAPI()

# CORS
origins = ["http://localhost:5173"]
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


@app.get("/")
def root():
    return {"message": "WisEnergy API running"}


# Scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(weekly_summary_aggregation, "cron", hour=0, minute=5, timezone=PH_TZ)
scheduler.add_job(total_energy_consumption, "cron", hour=0, minute=10, timezone=PH_TZ)
scheduler.add_job(
    scheduled_prediction_update, "cron", hour=0, minute=20, timezone=PH_TZ
)
scheduler.add_job(hourly_summary_update, "cron", minute=0, timezone=PH_TZ)
scheduler.start()
