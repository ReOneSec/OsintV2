# database.py
import pymongo
import configparser
from datetime import datetime
from urllib.parse import quote_plus

# --- CONFIGURATION ---
config = configparser.ConfigParser(interpolation=None)
config.read_file(open('config.ini'))

# --- Read separate credentials from config ---
DB_USERNAME = config['MONGODB']['DB_USERNAME']
DB_PASSWORD = config['MONGODB']['DB_PASSWORD']
CLUSTER_URL = config['MONGODB']['CLUSTER_URL']

# --- Escape username and password and build the final connection string ---
ESCAPED_USERNAME = quote_plus(DB_USERNAME)
ESCAPED_PASSWORD = quote_plus(DB_PASSWORD)
CONNECTION_STRING = f"mongodb+srv://{ESCAPED_USERNAME}:{ESCAPED_PASSWORD}@{CLUSTER_URL}/?authSource=admin&retryWrites=true&w=majority"

# --- MONGODB CLIENT SETUP ---
client = pymongo.MongoClient(CONNECTION_STRING)
db = client.get_database("bot_db")
users_collection = db.get_collection("users")
api_keys_collection = db.get_collection("api_keys")

def add_or_update_user(user_id: int, expiry_date: datetime, plan_type: str):
    """
    Adds a new user or updates an existing one, setting their plan type and expiry date.
    """
    users_collection.update_one(
        {"_id": user_id},
        {
            "$set": {
                "expiry_date": expiry_date,
                "plan_type": plan_type
            }
        },
        upsert=True
    )

def get_user_subscription(user_id: int) -> dict | None:
    """
    Retrieves a user's full subscription details (plan_type, expiry_date).
    Returns a dictionary or None if the user is not found.
    """
    return users_collection.find_one({"_id": user_id})


def get_all_active_users() -> list[int]:
    """
    Retrieves a list of all user IDs with an active, non-expired subscription.
    """
    active_user_docs = users_collection.find(
        {"expiry_date": {"$gt": datetime.now()}},
        {"_id": 1} # Only return the _id field
    )
    return [doc["_id"] for doc in active_user_docs]

# (add_api_keys and get_api_keys functions remain unchanged)
def add_api_keys(keys_to_add: list[str]) -> int:
    if not keys_to_add: return 0
    api_keys_collection.update_one(
        {"_id": "key_pool"},
        {"$addToSet": {"keys": {"$each": keys_to_add}}},
        upsert=True
    )
    return len(keys_to_add)

def get_api_keys() -> list[str]:
    key_document = api_keys_collection.find_one({"_id": "key_pool"})
    if key_document and "keys" in key_document:
        return key_document["keys"]
    return []
    
