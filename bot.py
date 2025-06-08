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
from api_manager import ApiKeyManager  # Import the new manager

# --- CONFIGURATION AND LOGGING SETUP ---
config = configparser.ConfigParser()
try:
    config.read_file(open('config.ini'))
except FileNotFoundError:
    print("FATAL: config.ini not found. Please create it. Exiting.")
    exit()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# --- CREDENTIALS AND SETTINGS ---
try:
    BOT_TOKEN = config['TELEGRAM']['BOT_TOKEN']
    API_URL = config['LEAKOSINT']['API_URL']
    LANG = config['LEAKOSINT'].get('LANG', 'ru')
    LIMIT = config['LEAKOSINT'].getint('LIMIT', 300)
    ADMIN_IDS = {int(admin_id.strip()) for admin_id in config['ADMIN']['ADMIN_IDS'].split(',')}
except KeyError as e:
    logger.fatal(f"Configuration Error: {e}")
    exit()

# --- INITIALIZATION ---
bot = telebot.TeleBot(BOT_TOKEN)
key_manager = ApiKeyManager()  # Instantiate the API key manager
cash_reports = TTLCache(maxsize=500, ttl=3600)
user_timestamps = {}

# --- CONSTANTS ---
CALLBACK_PREFIX_PAGE = "/page "
CALLBACK_DELETE = "/delete"
USER_COOLDOWN = 3
MAX_MESSAGE_LENGTH = 4096
BROADCAST_SLEEP_TIME = 0.1

# --- HELPER FUNCTIONS ---
def generate_report(query: str, query_id: int) -> tuple[list | None, str | None]:
    api_key_to_use = key_manager.get_next_key()

    if not api_key_to_use:
        logger.error("No available API keys to process a request.")
        return None, "The bot is not configured with any API keys. Please contact an admin."

    logger.info(f"Making request for query '{query}' with a rotated API key.")
    data = {"token": api_key_to_use, "request": query.split("\n")[0], "limit": LIMIT, "lang": LANG}
    try:
        # (Rest of the function is the same as before)
        response = requests.post(API_URL, json=data, timeout=30)
        response.raise_for_status()
        response_json = response.json()
    except requests.exceptions.RequestException:
        return None, "A network error occurred."
    except requests.exceptions.JSONDecodeError:
        return None, "The search service returned an invalid response."
    if "Error code" in response_json:
        error_detail = response_json.get('Error detail', 'No detail')
        logger.error(f"API Error with key ending in '...{api_key_to_use[-4:]}': {error_detail}")
        return None, f"An API error occurred: {error_detail}"
    if not response_json.get("List"):
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
        report_pages.append(full_text)
    if report_pages:
        cash_reports[str(query_id)] = report_pages
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

# --- TELEGRAM BOT HANDLERS ---
# (/start, /help, /status, /add, /broadcast handlers remain the same)
@bot.message_handler(commands=["start", "help"])
def send_welcome(message: Message):
    welcome_text = (
        "<b>Welcome to the LeakOsint Bot!</b>\n\n"
        "This bot allows you to search for data in public leaks.\n"
        "To use the bot, you need an active subscription.\n\n"
        "<b>Commands:</b>\n"
        "/status - Check your current subscription status.\n"
        "/help - Show this message again."
    )
    bot.reply_to(message, welcome_text, parse_mode="html")

@bot.message_handler(commands=["status"])
def check_status(message: Message):
    user_id = message.from_user.id
    expiry_date = database.get_user_subscription(user_id)
    if expiry_date and expiry_date > datetime.now():
        days_left = (expiry_date - datetime.now()).days
        bot.reply_to(message, f"✅ Your subscription is active.\nIt expires on: {expiry_date.strftime('%Y-%m-%d')}. ({days_left} days left).")
    else:
        bot.reply_to(message, "❌ You do not have an active subscription. Please contact an admin to get access.")

@bot.message_handler(commands=["add"])
def add_user(message: Message):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS: return
    try:
        parts = message.text.split()
        if len(parts) != 3: raise ValueError
        user_id_to_add, days = int(parts[1]), int(parts[2])
        expiry_date = datetime.now() + timedelta(days=days)
        database.add_or_update_user(user_id_to_add, expiry_date)
        success_message = f"✅ Success!\nUser `{user_id_to_add}` now has access for *{days} days*.\nExpires on: `{expiry_date.strftime('%Y-%m-%d')}`."
        bot.reply_to(message, success_message, parse_mode="Markdown")
        try:
            bot.send_message(user_id_to_add, f"🎉 Great news! An admin has granted you access for {days} days. Use /status to see your expiry date.")
        except Exception as e:
            logger.warning(f"Could not notify user {user_id_to_add}: {e}")
    except (ValueError, IndexError):
        bot.reply_to(message, "⚠️ Invalid format. Use: `/add <user_id> <days>`")

### --- NEW /addapi COMMAND --- ###
@bot.message_handler(commands=['addapi'])
def add_api_keys_command(message: Message):
    """Admin command to dynamically add new LeakOsint API keys."""
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        bot.reply_to(message, "⚠️ This command is for admins only.")
        return

    # Extract keys from the message text, e.g., "/addapi key1,key2,key3"
    try:
        keys_string = message.text.split(maxsplit=1)[1]
        keys_to_add = [key.strip() for key in keys_string.split(',') if key.strip()]
    except IndexError:
        bot.reply_to(message, "⚠️ **Usage:** `/addapi <key1>,<key2>,...`\nPlease provide at least one key.")
        return

    if not keys_to_add:
        bot.reply_to(message, "⚠️ No valid keys found in your message.")
        return

    num_added = key_manager.add_keys(keys_to_add)
    bot.reply_to(message, f"✅ Operation complete. Added **{num_added}** new API key(s) to the pool. The bot is now using the updated list.")


@bot.message_handler(commands=['broadcast'])
def broadcast_message(message: Message):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS: return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ **Usage:** Please reply to the message you want to broadcast with the `/broadcast` command.")
        return
    users_to_broadcast = database.get_all_active_users()
    if not users_to_broadcast:
        bot.reply_to(message, "ℹ️ There are no active subscribers to broadcast to.")
        return
    bot.reply_to(message, f"📢 Starting broadcast to {len(users_to_broadcast)} users...")
    success_count, fail_count = 0, 0
    for user_id in users_to_broadcast:
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=message.reply_to_message.chat.id, message_id=message.reply_to_message.message_id)
            success_count += 1
        except ApiTelegramException as e:
            fail_count += 1
            logger.warning(f"Failed to send broadcast to user {user_id}: {e}")
        time.sleep(BROADCAST_SLEEP_TIME)
    final_report = f"Broadcast complete!\n\n✅ Sent successfully: {success_count}\n❌ Failed (e.g., bot blocked): {fail_count}"
    bot.send_message(admin_id, final_report)

@bot.message_handler(content_types=['text'])
def handle_message(message: Message):
    # (This handler remains the same)
    user_id = message.from_user.id
    expiry_date = database.get_user_subscription(user_id)
    if not expiry_date or expiry_date < datetime.now():
        bot.reply_to(message, "❌ Your subscription has expired or you don't have one. Please contact an admin. Use /status to check.")
        return
    current_time = time.time()
    if user_id in user_timestamps and (current_time - user_timestamps[user_id]) < USER_COOLDOWN:
        bot.reply_to(message, f"Please wait {USER_COOLDOWN} seconds.")
        return
    user_timestamps[user_id] = current_time
    query_id = randint(0, 9_999_999)
    wait_message = bot.reply_to(message, "⏳ Searching, please wait...")
    report_pages, error = generate_report(message.text, query_id)
    bot.delete_message(chat_id=message.chat.id, message_id=wait_message.message_id)
    if error:
        bot.reply_to(message, f"⚠️ Error: {error}")
    elif not report_pages:
        bot.reply_to(message, "✅ No results found for your query.")
    else:
        markup = create_inline_keyboard(query_id, 0, len(report_pages))
        try:
            bot.send_message(message.chat.id, report_pages[0], parse_mode="html", reply_markup=markup)
        except ApiTelegramException:
            plain_text = report_pages[0].replace("<b>", "").replace("</b>", "")
            bot.send_message(message.chat.id, text=plain_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call: CallbackQuery):
    # (This handler remains the same)
    if call.data.startswith(CALLBACK_PREFIX_PAGE):
        try: _, query_id_str, page_id_str = call.data.split(" "); page_id = int(page_id_str)
        except (ValueError, IndexError): return
        if query_id_str not in cash_reports:
            bot.edit_message_text("This query has expired.", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            return
        report_pages = cash_reports[query_id_str]
        markup = create_inline_keyboard(query_id_str, page_id, len(report_pages))
        try: bot.edit_message_text(report_pages[page_id], chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="html", reply_markup=markup)
        except ApiTelegramException: pass
    elif call.data == CALLBACK_DELETE:
        try: bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except ApiTelegramException: pass
    elif call.data == "no_action":
        bot.answer_callback_query(call.id)

if __name__ == '__main__':
    logger.info("Bot starting with all systems enabled...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0)
        except Exception as e:
            logger.critical(f"An unhandled exception occurred in the polling loop: {e}", exc_info=True)
            time.sleep(5)
