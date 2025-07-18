# bot.py
import telebot
import requests
import logging
import configparser
import time
from random import randint
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from telebot.apihelper import ApiTelegramException
from cachetools import TTLCache

import database
from api_manager import ApiKeyManager

# --- CONFIGURATION AND LOGGING SETUP ---
config = configparser.ConfigParser(interpolation=None)
config.read_file(open('config.ini'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# --- CREDENTIALS AND SETTINGS ---
try:
    BOT_TOKEN = config['TELEGRAM']['BOT_TOKEN']
    API_URL = config['LEAKOSINT']['API_URL']
    LANG = config['LEAKOSINT'].get('LANG', 'ru')
    LIMIT = config['LEAKOSINT'].getint('LIMIT', 300)
    ADMIN_IDS = {int(admin_id.strip()) for admin_id in config['ADMIN']['ADMIN_IDS'].split(',')}
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS not configured. Admin commands will not be available.")
except KeyError as e:
    logger.fatal(f"Configuration Error: Missing section or key in config.ini: {e}")
    exit(1)

# --- INITIALIZATION ---
BOT_START_TIME = datetime.now()
bot = telebot.TeleBot(BOT_TOKEN)
key_manager = ApiKeyManager()
cash_reports = TTLCache(maxsize=500, ttl=3600)
user_timestamps = {}

# --- CONSTANTS ---
CALLBACK_PREFIX_PAGE = "/page "
CALLBACK_DELETE = "/delete"
CALLBACK_DELETE_API_KEY_PREFIX = "/delapi "
PREMIUM_COOLDOWN = 3
TRIAL_COOLDOWN = 1800
MAX_MESSAGE_LENGTH = 4096
BROADCAST_SLEEP_TIME = 0.1

# --- HELPER FUNCTIONS ---
def format_uptime(duration: timedelta) -> str:
    days, remainder = divmod(duration.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days)}d, {int(hours)}h, {int(minutes)}m"

def generate_report(query: str, query_id: int) -> tuple[list | None, str | None]:
    api_key_to_use = key_manager.get_next_key()
    if not api_key_to_use:
        logger.warning("No API keys available for search query.")
        return None, "The bot is not configured with any API keys. Please contact an admin."
    
    logger.info(f"Making request for query '{query[:50]}...' with a rotated API key (ending in '...{api_key_to_use[-4:]}').")
    
    data = {"token": api_key_to_use, "request": query.split("\n")[0], "limit": LIMIT, "lang": LANG}
    try:
        response = requests.post(API_URL, json=data, timeout=30)
        response.raise_for_status()
        response_json = response.json()
    except requests.exceptions.Timeout:
        logger.error(f"API request timed out for query '{query[:50]}...'.")
        return None, "The search service took too long to respond. Please try again."
    except requests.exceptions.ConnectionError:
        logger.error(f"Network connection error during API request for query '{query[:50]}...'.")
        return None, "A network error occurred while connecting to the search service."
    except requests.exceptions.RequestException as e:
        logger.error(f"General request error for query '{query[:50]}...': {e}")
        return None, f"An unexpected network error occurred: {e}"
    except requests.exceptions.JSONDecodeError:
        logger.error(f"The search service returned an invalid JSON response for query '{query[:50]}...'.")
        return None, "The search service returned an invalid response."

    if "Error code" in response_json:
        error_detail = response_json.get('Error detail', 'No detail provided by API.')
        logger.error(f"API Error with key ending in '...{api_key_to_use[-4:]}': {error_detail}")
        return None, f"An API error occurred: {error_detail}"
    
    if not response_json.get("List"):
        logger.info(f"No results found for query '{query[:50]}...'.")
        return [], None

    report_pages = []
    for database_name, details in response_json["List"].items():
        text_parts = [f"<b>{database_name}</b>", ""]
        text_parts.append(details.get("InfoLeak", "") + "\n")
        
        if "Data" in details:
            for report_data in details["Data"]:
                for column_name, value in report_data.items():
                    text_parts.append(f"<b>{column_name}</b>:  {value}")
                text_parts.append("")
        
        full_text = "\n".join(text_parts)
        
        if len(full_text) > MAX_MESSAGE_LENGTH:
            full_text = full_text[:MAX_MESSAGE_LENGTH - 100] + "\n\n[...Message truncated...]"
            logger.warning(f"Truncated message for query '{query[:50]}...' due to length.")
        
        report_pages.append(full_text)
    
    if report_pages:
        cash_reports[str(query_id)] = report_pages
        logger.info(f"Generated {len(report_pages)} report pages for query_id {query_id}.")
    
    return report_pages, None

def create_inline_keyboard(query_id: int, page_id: int, count_page: int) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    if count_page > 1:
        prev_page = page_id - 1 if page_id > 0 else count_page - 1
        next_page = page_id + 1 if page_id < count_page - 1 else 0
        markup.row(
            InlineKeyboardButton(text="<<", callback_data=f"{CALLBACK_PREFIX_PAGE}{query_id} {prev_page}"),
            InlineKeyboardButton(text=f"{page_id + 1}/{count_page}", callback_data="no_action"),
            InlineKeyboardButton(text=">>", callback_data=f"{CALLBACK_PREFIX_PAGE}{query_id} {next_page}")
        )
    markup.row(InlineKeyboardButton(text="🗑️ Delete", callback_data=CALLBACK_DELETE))
    return markup

def create_api_key_keyboard(api_keys: list[str]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    if not api_keys:
        return markup

    for key in api_keys:
        display_key = f"...{key[-8:]}" if len(key) > 8 else key
        markup.add(InlineKeyboardButton(text=f"Delete Key: {display_key}", callback_data=f"{CALLBACK_DELETE_API_KEY_PREFIX}{key}"))
    return markup


# --- TELEGRAM BOT HANDLERS ---

@bot.message_handler(commands=["start"])
def send_welcome(message: Message):
    welcome_text = (
        "<b>Welcome to the LeakOsint Bot!</b>\n\n"
        "To see a list of available commands, please use /help."
    )
    bot.reply_to(message, welcome_text, parse_mode="html")
    logger.info(f"Sent welcome message to user {message.from_user.id}")

@bot.message_handler(commands=["help"])
def send_help(message: Message):
    user_id = message.from_user.id
    help_text = (
        "<b>Here is a list of available commands:</b>\n\n"
        "<b><u>User Commands</u></b>\n"
        "• `/start` - Get the welcome message.\n"
        "• `/help` - Show this command list.\n"
        "• `/status` - Check your subscription status."
    )
    if user_id in ADMIN_IDS:
        admin_help_text = (
            "\n\n"
            "<b><u>Admin Commands</u></b>\n"
            "• `/stat` - View bot usage statistics.\n"
            "• `/add &lt;user_id&gt; &lt;days&gt;` - Grant a premium subscription.\n"
            "• `/trial &lt;user_id&gt; &lt;hours&gt;` - Grant a temporary trial.\n"
            "• `/addapi &lt;key1&gt;,&lt;key2&gt;` - Add new API keys.\n"
            "• `/viewapi` - View and manage current API keys.\n" # Added to help section
            "• `/broadcast` (as reply) - Send a message to all subscribers."
        )
        help_text += admin_help_text
    bot.reply_to(message, help_text, parse_mode="html")
    logger.info(f"Sent help message to user {user_id}")

@bot.message_handler(commands=["status"])
def check_status(message: Message):
    user_id = message.from_user.id
    subscription_info = database.get_user_subscription(user_id)
    if subscription_info and subscription_info.get("expiry_date") and subscription_info["expiry_date"] > datetime.now():
        plan_type = subscription_info.get("plan_type", "premium").title()
        expiry_date = subscription_info["expiry_date"]
        days_left = (expiry_date - datetime.now()).days
        bot.reply_to(message, f"✅ Your **{plan_type} Plan** is active.\nIt expires on: {expiry_date.strftime('%Y-%m-%d %H:%M')}. ({days_left} days left).", parse_mode="Markdown")
        logger.info(f"User {user_id} checked status: Active {plan_type} plan.")
    else:
        bot.reply_to(message, "❌ You do not have an active subscription.")
        logger.info(f"User {user_id} checked status: No active subscription.")

@bot.message_handler(commands=['stat'])
def send_stats(message: Message):
    admin_id = message.from_user.id
    logger.debug(f"Received /stat command from user ID {admin_id}")

    if admin_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user ID {admin_id} for /stat.")
        bot.reply_to(message, "🚫 You are not authorized to use this command.")
        return
    
    total_users = database.get_total_user_count()
    active_users = len(database.get_all_active_users())
    total_requests = database.get_total_requests()
    
    uptime = datetime.now() - BOT_START_TIME
    
    stats_text = (
        f"<b>📊 Bot Statistics</b>\n\n"
        f"<b>Uptime:</b> {format_uptime(uptime)}\n"
        f"<b>Total Users:</b> {total_users} (in database)\n"
        f"<b>Active Subscribers:</b> {active_users}\n"
        f"<b>Total Requests Processed:</b> {total_requests}"
    )
    bot.reply_to(message, stats_text, parse_mode="html")
    logger.info(f"Admin {admin_id} viewed bot statistics.")


# Dedicated handler for /viewapi to ensure it's caught as a command
@bot.message_handler(commands=["viewapi"])
def view_api_keys_command(message: Message):
    admin_id = message.from_user.id
    logger.debug(f"Received /viewapi command from user ID {admin_id}")

    if admin_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user ID {admin_id} for /viewapi.")
        bot.reply_to(message, "🚫 You are not authorized to use this command.")
        return
    
    logger.info(f"Admin {admin_id} requested /viewapi.")
    api_keys = database.get_api_keys()
    logger.debug(f"Fetched API keys for /viewapi: {len(api_keys)} keys found.")
    
    if not api_keys:
        bot.reply_to(message, "ℹ️ No API keys currently stored.")
        logger.info(f"No API keys found for /viewapi request from {admin_id}.")
        return

    response_text = "<b>Current API Keys:</b>\n\n"
    for i, key in enumerate(api_keys):
        response_text += f"{i+1}. `{key}`\n"
    
    markup = create_api_key_keyboard(api_keys)
    try:
        bot.reply_to(message, response_text, parse_mode="html", reply_markup=markup)
        logger.info(f"Sent API key list to admin {admin_id}.")
    except ApiTelegramException as e:
        logger.error(f"Failed to send API key list to admin {admin_id}: {e}")
        bot.reply_to(message, "⚠️ An error occurred while sending the key list. Please check logs.")


# Handler for other admin commands that remain grouped
@bot.message_handler(commands=["add", "trial", "addapi", "broadcast"])
def handle_other_admin_commands(message: Message):
    admin_id = message.from_user.id
    logger.debug(f"Received admin command '{message.text}' from user ID {admin_id}")

    if admin_id not in ADMIN_IDS:
        logger.warning(f"Unauthorized access attempt by user ID {admin_id} for command '{message.text}'")
        bot.reply_to(message, "🚫 You are not authorized to use this command.")
        return
    
    command = message.text.split()[0].lower()
    logger.info(f"Admin {admin_id} is executing command: {command}")
    
    if command == '/add':
        try:
            parts = message.text.split()
            user_id_to_add = int(parts[1])
            days = int(parts[2])
            expiry_date = datetime.now() + timedelta(days=days)
            database.add_or_update_user(user_id_to_add, expiry_date, plan_type="premium")
            success_message = f"✅ Success!\nUser `{user_id_to_add}` now has a **Premium Plan** for *{days} days*."
            bot.reply_to(message, success_message, parse_mode="Markdown")
            logger.info(f"Admin {admin_id} granted premium to user {user_id_to_add} for {days} days.")
            try: 
                bot.send_message(user_id_to_add, f"🎉 An admin has granted you a Premium subscription for {days} days! Enjoy unlimited searches within your cooldown period.")
            except ApiTelegramException as e: 
                logger.warning(f"Could not notify user {user_id_to_add} about premium grant: {e}")
        except (ValueError, IndexError): 
            bot.reply_to(message, "⚠️ Invalid format. Use: `/add <user_id> <days>`")
            logger.warning(f"Admin {admin_id} used invalid format for /add: {message.text}")

    elif command == '/trial':
        try:
            parts = message.text.split()
            user_id_to_add = int(parts[1])
            hours = int(parts[2])
            expiry_date = datetime.now() + timedelta(hours=hours)
            database.add_or_update_user(user_id_to_add, expiry_date, plan_type="trial")
            success_message = f"✅ Success!\nUser `{user_id_to_add}` now has a **Trial Plan** for *{hours} hour(s)*."
            bot.reply_to(message, success_message, parse_mode="Markdown")
            logger.info(f"Admin {admin_id} granted trial to user {user_id_to_add} for {hours} hours.")
            try: 
                bot.send_message(user_id_to_add, f"🎉 You have a trial subscription for {hours} hour(s)! Trial users can make one request every {round(TRIAL_COOLDOWN/60)} minutes.")
            except ApiTelegramException as e: 
                logger.warning(f"Could not notify user {user_id_to_add} about trial grant: {e}")
        except (ValueError, IndexError): 
            bot.reply_to(message, "⚠️ Invalid format. Use: `/trial <user_id> <hours>`")
            logger.warning(f"Admin {admin_id} used invalid format for /trial: {message.text}")

    elif command == '/addapi':
        try:
            keys_string = message.text.split(maxsplit=1)[1]
            keys_to_add = [key.strip() for key in keys_string.split(',') if key.strip()]
            if not keys_to_add: 
                raise ValueError("No keys provided.")
            
            num_added = key_manager.add_keys(keys_to_add)
            bot.reply_to(message, f"✅ Operation complete. Added **{num_added}** new API key(s) to the pool.")
            logger.info(f"Admin {admin_id} added {num_added} new API keys.")
        except (IndexError, ValueError) as e: 
            bot.reply_to(message, "⚠️ **Usage:** `/addapi <key1>,<key2>,...` (Error: " + str(e) + ")")
            logger.warning(f"Admin {admin_id} used invalid format for /addapi: {message.text}. Error: {e}")

    elif command == '/broadcast':
        if not message.reply_to_message:
            bot.reply_to(message, "⚠️ **Usage:** Reply to a message with `/broadcast`.")
            logger.warning(f"Admin {admin_id} tried /broadcast without replying to a message.")
            return
        
        users_to_broadcast = database.get_all_active_users()
        if not users_to_broadcast:
            bot.reply_to(message, "ℹ️ There are no active subscribers to broadcast to.")
            logger.info(f"Admin {admin_id} tried /broadcast, but no active users found.")
            return
        
        bot.reply_to(message, f"📢 Starting broadcast to {len(users_to_broadcast)} users...")
        logger.info(f"Admin {admin_id} started broadcast to {len(users_to_broadcast)} users.")
        success_count, fail_count = 0, 0
        for user_id in users_to_broadcast:
            try:
                bot.copy_message(chat_id=user_id, from_chat_id=message.reply_to_message.chat.id, message_id=message.reply_to_message.message_id)
                success_count += 1
            except ApiTelegramException as e:
                fail_count += 1
                logger.warning(f"Failed to send broadcast to user {user_id}: {e}")
            time.sleep(BROADCAST_SLEEP_TIME)
        
        final_report = f"Broadcast complete!\n\n✅ Sent: {success_count}\n❌ Failed: {fail_count}"
        bot.send_message(admin_id, final_report)
        logger.info(f"Broadcast from admin {admin_id} finished. Sent: {success_count}, Failed: {fail_count}.")


# This general text handler MUST be defined AFTER all specific command handlers
@bot.message_handler(content_types=['text'])
def handle_message(message: Message):
    user_id = message.from_user.id
    logger.info(f"Received text message from user {user_id}: '{message.text[:50]}...'")

    subscription_info = database.get_user_subscription(user_id)
    if not subscription_info or subscription_info.get("expiry_date") is None or subscription_info["expiry_date"] < datetime.now():
        bot.reply_to(message, "❌ Your subscription has expired or you don't have one.")
        logger.info(f"Blocked user {user_id} due to expired/missing subscription.")
        return
    
    plan_type = subscription_info.get("plan_type", "premium")
    cooldown = TRIAL_COOLDOWN if plan_type == 'trial' else PREMIUM_COOLDOWN
    current_time = time.time()

    if user_id in user_timestamps and (current_time - user_timestamps[user_id]) < cooldown:
        time_left = cooldown - (current_time - user_timestamps[user_id])
        if plan_type == 'trial':
            bot.reply_to(message, f"⏳ Trial members are limited. Please wait another {round(time_left / 60)} minute(s).")
            logger.info(f"Blocked trial user {user_id} due to cooldown. Time left: {round(time_left / 60)} min.")
        else:
            bot.reply_to(message, f"Please wait {round(time_left)} seconds.")
            logger.info(f"Blocked premium user {user_id} due to cooldown. Time left: {round(time_left)} sec.")
        return
    
    user_timestamps[user_id] = current_time
    
    database.increment_total_requests()
    logger.debug(f"Incremented total requests. User {user_id} made a request.")
    
    query_id = randint(0, 9_999_999)
    wait_message = bot.reply_to(message, "⏳ Searching, please wait...")
    
    report_pages, error = generate_report(message.text, query_id)
    
    try:
        bot.delete_message(chat_id=message.chat.id, message_id=wait_message.message_id)
    except ApiTelegramException as e:
        logger.warning(f"Could not delete wait message {wait_message.message_id} for user {message.chat.id}: {e}")

    if error:
        bot.reply_to(message, f"⚠️ Error: {error}")
        logger.error(f"Search failed for user {user_id}, query '{message.text[:50]}...': {error}")
    elif not report_pages:
        bot.reply_to(message, "✅ No results found for your query.")
        logger.info(f"No results for user {user_id}, query '{message.text[:50]}...'.")
    else:
        markup = create_inline_keyboard(query_id, 0, len(report_pages))
        try:
            bot.send_message(message.chat.id, report_pages[0], parse_mode="html", reply_markup=markup)
            logger.info(f"Sent {len(report_pages)} report pages to user {user_id} for query '{message.text[:50]}...'.")
        except ApiTelegramException as e:
            logger.warning(f"Failed to send HTML formatted message to user {message.chat.id} ({message.message_id}): {e}. Sending as plain text.")
            plain_text = report_pages[0].replace("<b>", "").replace("</b>", "")
            bot.send_message(message.chat.id, text=plain_text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call: CallbackQuery):
    logger.debug(f"Callback received: {call.data} from user {call.from_user.id}")

    if call.data.startswith(CALLBACK_PREFIX_PAGE):
        try: 
            _, query_id_str, page_id_str = call.data.split(" ")
            page_id = int(page_id_str)
        except (ValueError, IndexError): 
            logger.error(f"Malformed page callback data: {call.data}")
            bot.answer_callback_query(call.id, "Error: Invalid page data.")
            return

        if query_id_str not in cash_reports:
            bot.edit_message_text("This query has expired. Please perform a new search.", 
                                  chat_id=call.message.chat.id, 
                                  message_id=call.message.message_id, 
                                  reply_markup=None)
            bot.answer_callback_query(call.id, "Query expired.")
            logger.info(f"Query {query_id_str} expired for user {call.from_user.id}.")
            return
        
        report_pages = cash_reports[query_id_str]
        page_id = page_id % len(report_pages)
        
        markup = create_inline_keyboard(query_id_str, page_id, len(report_pages))
        try: 
            bot.edit_message_text(report_pages[page_id], 
                                  chat_id=call.message.chat.id, 
                                  message_id=call.message.message_id, 
                                  parse_mode="html", 
                                  reply_markup=markup)
            bot.answer_callback_query(call.id)
            logger.info(f"User {call.from_user.id} navigated to page {page_id} for query {query_id_str}.")
        except ApiTelegramException as e: 
            logger.warning(f"Failed to edit message for pagination (user {call.from_user.id}, message {call.message.message_id}): {e}")
            bot.answer_callback_query(call.id, "Could not update page. Try again.")
    
    elif call.data == CALLBACK_DELETE:
        try: 
            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
            bot.answer_callback_query(call.id, "Message deleted.")
            logger.info(f"User {call.from_user.id} deleted message {call.message.message_id}.")
        except ApiTelegramException as e: 
            logger.warning(f"Failed to delete message {call.message.message_id} for user {call.from_user.id}: {e}")
            bot.answer_callback_query(call.id, "Could not delete message. It might be too old.")

    elif call.data.startswith(CALLBACK_DELETE_API_KEY_PREFIX):
        if call.from_user.id not in ADMIN_IDS:
            logger.warning(f"Unauthorized API key deletion attempt by user {call.from_user.id}.")
            bot.answer_callback_query(call.id, "You are not authorized to perform this action.")
            return

        api_key_to_delete = call.data.split(CALLBACK_DELETE_API_KEY_PREFIX, 1)[1]
        
        bot.edit_message_text(
            f"⏳ Processing deletion for key `...{api_key_to_delete[-8:]}`...",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id, "Deleting key...")

        if key_manager.delete_key(api_key_to_delete):
            logger.info(f"Admin {call.from_user.id} successfully deleted API key ending in '...{api_key_to_delete[-8:]}'.")
            
            updated_api_keys = database.get_api_keys()
            if updated_api_keys:
                response_text = "<b>Current API Keys:</b>\n\n"
                for i, key in enumerate(updated_api_keys):
                    response_text += f"{i+1}. `{key}`\n"
                updated_markup = create_api_key_keyboard(updated_api_keys)
                
                bot.edit_message_text(
                    f"✅ API key ending in `...{api_key_to_delete[-8:]}` deleted.\n\n" + response_text,
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="html",
                    reply_markup=updated_markup
                )
            else:
                bot.edit_message_text(
                    f"✅ API key ending in `...{api_key_to_delete[-8:]}` deleted.\n\nℹ️ No API keys remaining.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="Markdown",
                    reply_markup=None
                )
        else:
            logger.error(f"Failed to delete API key ending in '...{api_key_to_delete[-8:]}' for admin {call.from_user.id}. Key not found or DB error.")
            bot.edit_message_text(
                f"❌ Failed to delete API key ending in `...{api_key_to_delete[-8:]}`. It might no longer exist or an error occurred.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
    
    elif call.data == "no_action":
        bot.answer_callback_query(call.id)

if __name__ == '__main__':
    logger.info("Bot starting with all systems enabled...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0)
        except Exception as e:
            logger.critical(f"An unhandled exception occurred in the polling loop: {e}", exc_info=True)
            logger.info("Restarting bot polling in 5 seconds...")
            time.sleep(5)
