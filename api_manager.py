import itertools
import database
import logging

logger = logging.getLogger(__name__)

class ApiKeyManager:
    def __init__(self):
        """Initializes the manager, loading keys from the database."""
        self.keys = []
        self.key_cycler = None
        self.reload_keys()

    def reload_keys(self):
        """Fetches all keys from the database and rebuilds the key cycler."""
        self.keys = database.get_api_keys()
        if self.keys:
            self.key_cycler = itertools.cycle(self.keys)
            logger.info(f"Successfully loaded {len(self.keys)} API keys into the pool.")
        else:
            self.key_cycler = None
            logger.warning("No API keys found in the database. The bot cannot process search queries.")

    def add_keys(self, keys_to_add: list[str]) -> int:
        """Adds new keys to the database and reloads the in-memory pool."""
        if not keys_to_add:
            return 0

        num_added = database.add_api_keys(keys_to_add)
        if num_added > 0:
            logger.info(f"Admin added {num_added} new API keys. Reloading key pool.")
            self.reload_keys()

        return num_added

    def get_next_key(self) -> str | None:
        """Returns the next key from the rotation, or None if no keys are available."""
        if self.key_cycler:
            return next(self.key_cycler)
        return None

    def delete_key(self, key_to_delete: str) -> bool:
        """Deletes a specific key from the database and reloads the in-memory pool."""
        deleted = database.delete_api_key(key_to_delete)
        if deleted:
            logger.info(f"API key ending in '...{key_to_delete[-4:]}' deleted. Reloading key pool.")
            self.reload_keys()
        return deleted

