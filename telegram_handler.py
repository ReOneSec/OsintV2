import logging
import telebot
import time

class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id, level=logging.NOTSET):
        super().__init__(level)
        self.bot = telebot.TeleBot(token)
        self.chat_id = chat_id
        self.last_sent_time = 0
        self.min_interval = 2 # Minimum seconds between sending logs to avoid flooding

    def emit(self, record):
        # Prevent rapid-fire messages during critical errors
        current_time = time.time()
        if current_time - self.last_sent_time < self.min_interval:
            return

        log_entry = self.format(record)
        message_text = f"```\n{log_entry}\n```"

        try:
            # Only send ERROR, CRITICAL, or FATAL level messages to Telegram
            if record.levelno >= logging.ERROR:
                if len(message_text) > 4000: # Telegram message limit
                    message_text = message_text[:3997] + "```..." # Truncate and add ellipsis
                self.bot.send_message(self.chat_id, message_text, parse_mode="Markdown")
                self.last_sent_time = current_time
        except Exception as e:
            # Print to console if sending to Telegram fails
            print(f"Failed to send log to Telegram: {e}")
            print(f"Original log message: {log_entry}")

# Example of how you would use it (not part of this file, but for explanation)
# from telegram_handler import TelegramHandler
# telegram_handler = TelegramHandler(BOT_TOKEN, LOG_CHANNEL_ID, logging.ERROR)
# logger.addHandler(telegram_handler)
