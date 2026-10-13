from firebase_admin import credentials, db, firestore, auth, initialize_app
from ..config import FIREBASE_CREDS

cred = credentials.Certificate(FIREBASE_CREDS)
initialize_app(
    cred,
    {
        "databaseURL": "https://capstone-238eb-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)

fs = firestore.client()
