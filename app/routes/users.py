from fastapi import APIRouter, HTTPException
from typing import List
from firebase_admin import auth
from datetime import datetime
from ..utils.firebase import db
from ..models import User

router = APIRouter()


@router.get("/users", response_model=List[dict])
def get_all_users():
    users_ref = db.reference("/users").get() or {}

    # Firebase Auth
    auth_users = {}
    page = auth.list_users()
    while page:
        for user in page.users:
            auth_users[user.uid] = {"password": user.password_hash}
        page = page.get_next_page()

    users = []
    for uid, data in users_ref.items():
        merged = {
            "uid": uid,
            "email": data.get("email"),
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "location": data.get("location"),
            "created_at": data.get("created_at"),
            "date_modifed": data.get("date_modified"),
            "role": data.get("role"),
            "password": auth_users.get(uid, {}).get("password"),
        }
        users.append(merged)
    return users


@router.post("/users")
def add_user(user: User):
    try:
        now = datetime.now().strftime("%Y-%m-%d")
        firebase_user = auth.create_user(
            email=user.email,
            password="WisEnergy2025!",
            display_name=f"{user.first_name} {user.last_name}",
        )

        ref = db.reference("/users")
        user_id = firebase_user.uid
        payload = {
            "id": user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "location": user.location,
            "role": user.role,
            "date_created": now,
            "date_modified": now,
        }
        ref.child(user_id).set(payload)
        return {"status": "success", "data": payload}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
def edit_user(user_id: str, user: User):
    try:
        ref = db.reference(f"/users/{user_id}")
        existing = ref.get()
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")

        now = datetime.now().strftime("%Y-%m-%d")

        auth.update_user(
            user_id,
            email=user.email,
            display_name=f"{user.first_name} {user.last_name}",
        )

        updated_data = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "location": user.location,
            "role": user.role,
            "date_modified": now,
        }
        ref.update(updated_data)
        return {"status": "success", "data": {**existing, **updated_data}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
