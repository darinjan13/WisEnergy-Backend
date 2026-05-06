# WisEnergy Backend

FastAPI-based backend for WisEnergy, an energy monitoring and management platform.

## Tech Stack

- **Framework**: FastAPI
- **Server**: Uvicorn
- **Database**: Firebase Realtime Database
- **Authentication**: Firebase Auth
- **ML/Predictions**: Prophet (Facebook)
- **Email**: SendGrid
- **AI**: Google Gemini
- **Scheduler**: APScheduler

## Features

- **Authentication**: Email/password auth, OTP verification, password reset
- **User Management**: Admin login, user CRUD, scheduled account deletion
- **Device Management**: Device registration and tracking
- **Energy Predictions**: Daily, weekly, and monthly consumption predictions using Prophet
- **Electricity Rates**: City-based electricity rate management
- **AI Recommendations**: Gemini-powered energy usage recommendations and insights
- **Notifications**: Push notifications via Firebase
- **Subscriptions**: Subscription management via Paymongo
- **Reviews & Feedback**: User reviews and feedback collection

## Project Structure

```
WisEnergy-Backend/
├── app/
│   ├── main.py              # FastAPI app initialization
│   ├── config.py            # Environment configuration
│   ├── models/              # Pydantic models
│   │   ├── user_models.py
│   │   ├── paymongo_models.py
│   │   └── feedback_models.py
│   ├── routes/              # API endpoints
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── devices.py
│   │   ├── predictions.py
│   │   ├── rates.py
│   │   ├── recommendations.py
│   │   ├── notifications.py
│   │   ├── subscriptions.py
│   │   ├── paymongo.py
│   │   ├── reviews.py
│   │   └── feedback.py
│   ├── services/             # Business logic
│   │   ├── users.py
│   │   ├── predictions.py
│   │   ├── rates.py
│   │   ├── recommendations.py
│   │   ├── otp.py
│   │   ├── notifications.py
│   │   └── summaries.py
│   └── utils/               # Utilities
│       ├── firebase.py
│       ├── timezone.py
│       └── serviceAccount.json
├── requirements.txt
├── Procfile
└── README.md
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file with the following variables:

```
EMAIL_ADDRESS=your_email@example.com
EMAIL_PASSWORD=your_email_password
SENDGRID_API_KEY=your_sendgrid_api_key
GEMINI_API_KEY=your_gemini_api_key
FIREBASE_API_KEY=your_firebase_api_key
PAYMONGO_SECRET_KEY=your_paymongo_secret_key
```

## Running Locally

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## API Documentation

FastAPI provides interactive documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Scheduled Jobs

- **Hourly**: Update hourly energy summaries
- **Daily at 00:20 PHT**: Generate predictions for all users
- **Daily at 01:00 PHT**: Update electricity rates

## Deployment

Deployable on platforms like:
- Render
- Heroku
- Google Cloud Run

The `Procfile` is configured for deployment.