# database.py
import pymongo
import configparser
from datetime import datetime
from urllib.parse import quote_plus # Import the required function

# --- CONFIGURATION ---
config = configparser.ConfigParser(interpolation=None) # Keep interpolation=None
config.read_file(open('config.ini'))

# --- Read separate credentials from config ---
DB_USERNAME = config['MONGODB']['DB_USERNAME']
DB_PASSWORD = config['MONGODB']['DB_PASSWORD']
CLUSTER_URL = config['MONGODB']['CLUSTER_URL']

# --- Escape username and password and build the final connection string ---
ESCAPED_USERNAME = quote_plus(DB_USERNAME)
ESCAPED_PASSWORD = quote_plus(DB_PASSWORD)
CONNECTION_STRING = f"mongodb+srv://{ESCAPED_USERNAME}:{ESCAPED_PASSWORD}@{CLUSTER_URL}/?retryWrites=true&w=majority"

# --- MONGODB CLIENT SETUP ---
client = pymongo.MongoClient(CONNECTION_STRING)
db = client.get_database("bot_db")
users_collection = db.get_collection("users")
api_keys_collection = db.get_collection("api_keys")

def add_or_update_user(user_id: int, expiry_date: datetime):
    """
    Adds a new user or updates an existing one using their user_id as the primary key (_id).
    """
    users_collection.update_one(
        {"_id": user_id},
        {"$set": {"expiry_date": expiry_date}},
        upsert=True
    )

def get_user_subscription(user_id: int) -> datetime | None:
    """
    Retrieves a user's subscription expiry date from MongoDB.
    """
    user_document = users_collection.find_one({"_id": user_id})
    if user_document:
        return user_document.get("expiry_date")
    return None

def get_all_active_users() -> list[int]:
    """
    Retrieves a list of all user IDs with an active, non-expired subscription from MongoDB.
    """
    active_user_docs = users_collection.find(
        {"expiry_date": {"$gt": datetime.now()}}
    )
    return [doc["_id"] for doc in active_user_docs]

def add_api_keys(keys_to_add: list[str]) -> int:
    """
    Adds a list of keys to the key pool in the database.
    Uses $addToSet to prevent duplicate keys from being added.
    Returns the number of keys that were newly added.
    """
    if not keys_to_add:
        return 0

    result = api_keys_collection.update_one(
        {"_id": "key_pool"},  # Use a single document to store all keys
        {
            "$addToSet": {
                "keys": {"$each": keys_to_add}
            }
        },
        upsert=True
    )
    # This is a simplification, but effective for this use case.
    return len(keys_to_add)


def get_api_keys() -> list[str]:
    """Retrieves the list of all API keys from the database."""
    key_document = api_keys_collection.find_one({"_id": "key_pool"})

    if key_document and "keys" in key_document:
        return key_document["keys"]
    return []
    
