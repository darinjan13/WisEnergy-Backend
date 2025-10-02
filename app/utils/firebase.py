from firebase_admin import credentials, db, firestore, auth, initialize_app

cred = credentials.Certificate("serviceAccount.json")
initialize_app(
    cred,
    {
        "databaseURL": "https://wisenergy-11737-default-rtdb.asia-southeast1.firebasedatabase.app/"
    },
)

fs = firestore.client()
