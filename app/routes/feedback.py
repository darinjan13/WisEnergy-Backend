from fastapi import APIRouter, HTTPException
from datetime import datetime
from ..utils.firebase import db
from ..models.feedback_models import FeedbackStatusUpdate

router = APIRouter()


@router.get("/feedback")
def get_feedback():
    feedback_ref = db.reference("/feedback")
    feedback_data = feedback_ref.get()
    if not feedback_data:
        return []
    return [{"id": fid, **details} for fid, details in feedback_data.items()]


@router.patch("/feedback/{feedback_id}")
def update_feedback_status(feedback_id: str, update: FeedbackStatusUpdate):
    feedback_ref = db.reference(f"/feedback/{feedback_id}")
    feedback_data = feedback_ref.get()
    if not feedback_data:
        raise HTTPException(status_code=404, detail="Feedback not found")

    feedback_ref.update(
        {
            "status": update.status,
            "date_modified": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    return {
        "id": feedback_id,
        "status": update.status,
        "message": "Status updated successfully",
    }
