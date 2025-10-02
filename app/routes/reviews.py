from fastapi import APIRouter
from ..utils.firebase import db

router = APIRouter()


@router.get("/reviews")
def get_reviews():
    reviews_ref = db.reference("/reviews")
    reviews_data = reviews_ref.get()
    if not reviews_data:
        return []
    return [{"id": review_id, **details} for review_id, details in reviews_data.items()]


@router.get("/reviews/{review_id}")
def get_review(review_id: str):
    review_ref = db.reference(f"/reviews/{review_id}")
    review_data = review_ref.get()
    if not review_data:
        return {"error": "Review not found"}
    return {"id": review_id, **review_data}
