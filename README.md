# Advanced LeakOsint Telegram Bot

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)

An advanced, feature-rich Python Telegram bot that serves as a secure and scalable front-end for the LeakOsint API. This bot is designed for controlled access via a subscription model and includes powerful administrative tools for user management and communication.

## Core Features

-   **Premium Subscription System**: Access to the bot is managed through subscriptions. Admins can grant users access for a specific number of days.
-   **Persistent MongoDB Backend**: User data and subscriptions are securely stored in a scalable MongoDB Atlas database, ensuring data persistence across restarts.
-   **Admin Management**: Admins (defined in `config.ini`) have exclusive access to administrative commands.
-   **Dynamic Multi-API Key Management**: Admins can add or remove LeakOsint API keys at runtime, increasing request capacity and preventing downtime from rate limits.
-   **Broadcast System**: Admins can broadcast messages (including text, images, videos, and stickers) to all active subscribers. The system reports delivery status.
-   **Interactive UI**: Presents API results in a clean, paginated format with inline navigation buttons and a delete option.
-   **Robust & Secure**: Manages all sensitive credentials and settings externally, logs activity, handles errors gracefully, and includes user-side rate limiting.

## Commands

### User Commands

-   `/start` or `/help`: Shows the welcome message and lists commands.
-   `/status`: Allows users to check the status and expiry date of their subscription.

### Admin Commands

-   `/add <user_id> <days>`: Grants a subscription to a user for a specified number of days.
-   `/addapi <key1>,<key2>,...`: Adds one or more LeakOsint API keys to the active pool.
-   `/viewapi`: View Or Delete Stored LeakOsint API keys from the active pool.
-   `/broadcast` (as a reply): Broadcasts the replied-to message to all active subscribers.

## Setup and Installation

1.  **Prerequisites**:
    * Python 3.8+
    * A free [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) account.

2.  **Set up MongoDB Atlas**:
    * Create a free M0 cluster.
    * Create a database user (e.g., `botUser`) and save the password.
    * Whitelist your server's IP or `0.0.0.0/0` for universal access.
    * Get your connection string (URI).

3.  **Clone & Setup Project**:
    * Clone this repository.
    * Create the `config.ini` and `requirements.txt` files as shown in the project documentation.
    * Fill in your tokens, admin IDs, and MongoDB connection string in `config.ini`.

4.  **Install Dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

5.  **Run the Bot**:

    ```bash
    python bot.py
    ```

    The bot will connect to the database and start polling for messages. For continuous operation, use a process manager like `screen` or `systemd`.
    
