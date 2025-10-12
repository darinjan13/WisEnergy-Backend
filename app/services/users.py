# services/user.py
from firebase_admin import auth
from ..utils.firebase import db
from datetime import datetime


# def delete_user_job(uid: str):
#     """Deletes a user and all associated Firebase data."""
#     try:
#         print(f"[WisEnergy] ⚠️ Deleting user {uid} and all associated data...")

#         # Delete user-related data
#         db.reference(f"users/{uid}").delete()
#         db.reference(f"devices/{uid}").delete()
#         db.reference(f"usage/{uid}").delete()
#         db.reference(f"budget/{uid}").delete()
#         db.reference(f"appliances/{uid}").delete()
#         db.reference(f"daily_summary/{uid}").delete()
#         db.reference(f"daily_total_consumption/{uid}").delete()
#         db.reference(f"weekly_summary/{uid}").delete()
#         db.reference(f"weekly_total_consumption/{uid}").delete()
#         db.reference(f"monthly_summary/{uid}").delete()
#         db.reference(f"monthly_total_consumption/{uid}").delete()
#         db.reference(f"user_monthly_budget/{uid}").delete()
#         db.reference(f"predictions/{uid}").delete()
#         db.reference(f"tokens/{uid}").delete()
#         db.reference(f"notifications/{uid}").delete()

#         # Delete Firebase Auth account
#         auth.delete_user(uid)

#         print(f"[WisEnergy] ✅ Successfully deleted user {uid}")
#     except Exception as e:
#         print(f"[WisEnergy] ❌ Error deleting user {uid}: {e}")


# def check_scheduled_deletions():
#     """Scans for users whose deletion_date is due and deletes them."""
#     users_ref = db.reference("/users").get() or {}
#     now = datetime.now()

#     for uid, data in users_ref.items():
#         deletion_date = data.get("deletion_date")
#         if not deletion_date:
#             continue

#         try:
#             scheduled_time = datetime.strptime(deletion_date, "%Y-%m-%d %H:%M:%S")
#             if scheduled_time <= now:
#                 delete_user_job(uid)
#         except Exception as e:
#             print(f"[WisEnergy] ⚠️ Invalid deletion date for {uid}: {e}")
