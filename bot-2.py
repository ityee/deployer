"""
Telegram Bot — Heroku SESSION_ID Updater
Updates the SESSION_ID config var on a target Heroku app
via the Heroku Platform API.

Required environment variables:
    BOT_TOKEN        — Telegram bot token from @BotFather
    HEROKU_API_KEY   — Heroku API key with access to the target app
    TARGET_APP_NAME  — Name of the Heroku app to update
    ADMIN_CHAT_ID    — Telegram chat/user ID allowed to use this bot
"""

import os
import logging
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Environment Variables ────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
HEROKU_API_KEY  = os.environ["HEROKU_API_KEY"]
TARGET_APP_NAME = os.environ["TARGET_APP_NAME"]
ADMIN_CHAT_ID   = int(os.environ["ADMIN_CHAT_ID"])

# ─── Heroku API Helpers ───────────────────────────────────────────────────────

def heroku_headers() -> dict:
    """Return standard Heroku Platform API headers."""
    return {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept":        "application/vnd.heroku+json; version=3",
        "Content-Type":  "application/json",
    }


def update_heroku_config(key: str, value: str) -> tuple[bool, str]:
    """
    PATCH a single config var on the target Heroku app.

    Returns:
        (success: bool, message: str)
    """
    url = f"https://api.heroku.com/apps/{TARGET_APP_NAME}/config-vars"
    payload = {key: value}

    try:
        response = requests.patch(url, json=payload, headers=heroku_headers(), timeout=15)

        if response.status_code == 200:
            logger.info("Updated %s on app '%s' successfully.", key, TARGET_APP_NAME)
            return True, response.json()
        else:
            logger.error(
                "Heroku API error %s: %s", response.status_code, response.text
            )
            return False, f"HTTP {response.status_code}: {response.text}"

    except requests.exceptions.Timeout:
        logger.error("Heroku API request timed out.")
        return False, "Request to Heroku API timed out."
    except requests.exceptions.RequestException as exc:
        logger.error("Heroku API request failed: %s", exc)
        return False, str(exc)


# ─── Auth Guard ───────────────────────────────────────────────────────────────

def is_authorized(update: Update) -> bool:
    """Return True only if the sender matches ADMIN_CHAT_ID."""
    return update.effective_chat.id == ADMIN_CHAT_ID


async def deny(update: Update) -> None:
    """Send an unauthorized message and log the attempt."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "unknown"
    logger.warning("Unauthorized access attempt — chat_id=%s username=%s", chat_id, username)
    await update.message.reply_text("❌ You are not authorized to use this bot.")


# ─── Command Handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — Show bot info and available commands."""
    if not is_authorized(update):
        await deny(update)
        return

    text = (
        "🤖 *Heroku Config Updater Bot*\n\n"
        f"🎯 *Target App:* `{TARGET_APP_NAME}`\n\n"
        "📋 *Available Commands:*\n"
        "  `/start`  — Show this info\n"
        "  `/help`   — Usage guide\n"
        "  `/session <value>` — Update `SESSION_ID`\n"
        "  `/id`     — Show your Telegram chat ID\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — Show detailed usage guide."""
    if not is_authorized(update):
        await deny(update)
        return

    text = (
        "📖 *Usage Guide*\n\n"
        "*Update SESSION\\_ID on your Heroku app:*\n"
        "```\n/session YOUR_NEW_SESSION_VALUE\n```\n\n"
        "*Example:*\n"
        "```\n/session abc123xyz456\n```\n\n"
        "⚙️ The bot will immediately PATCH the config var on:\n"
        f"`{TARGET_APP_NAME}`\n\n"
        "♻️ *Note:* Heroku automatically restarts your app's "
        "dynos after a config var change, applying the new value.\n\n"
        "🔐 Only the authorized admin can use this bot."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/session <value> — Update SESSION_ID on the target Heroku app."""
    if not is_authorized(update):
        await deny(update)
        return

    # Validate that a value was provided
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage:* `/session <value>`\n\n"
            "Example: `/session abc123xyz456`",
            parse_mode="Markdown",
        )
        return

    new_value = " ".join(context.args).strip()

    if not new_value:
        await update.message.reply_text("⚠️ Session value cannot be empty.")
        return

    # Send a "working" indicator
    status_msg = await update.message.reply_text(
        f"⏳ Updating `SESSION_ID` on `{TARGET_APP_NAME}`...",
        parse_mode="Markdown",
    )

    success, result = update_heroku_config("SESSION_ID", new_value)

    if success:
        reply = (
            "✅ *SESSION\\_ID updated successfully!*\n\n"
            f"🎯 App: `{TARGET_APP_NAME}`\n"
            f"🔑 Key: `SESSION_ID`\n"
            f"📝 Value: `{new_value}`\n\n"
            "♻️ Heroku is restarting your dynos to apply the change."
        )
    else:
        reply = (
            "❌ *Failed to update SESSION\\_ID*\n\n"
            f"🎯 App: `{TARGET_APP_NAME}`\n"
            f"🔍 Error: `{result}`\n\n"
            "Check that your `HEROKU_API_KEY` and `TARGET_APP_NAME` are correct."
        )

    # Edit the "working" message with the final result
    await status_msg.edit_text(reply, parse_mode="Markdown")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/id — Return the sender's Telegram chat ID (useful for setting ADMIN_CHAT_ID)."""
    chat_id  = update.effective_chat.id
    username = update.effective_user.username or "N/A"
    fullname = update.effective_user.full_name or "N/A"

    text = (
        "🪪 *Your Telegram Info*\n\n"
        f"👤 Name: `{fullname}`\n"
        f"🔖 Username: `@{username}`\n"
        f"🆔 Chat ID: `{chat_id}`\n\n"
        "Use this Chat ID as `ADMIN_CHAT_ID` in your Heroku config vars."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Error Handler ────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all unhandled exceptions."""
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Build and start the bot using polling."""
    logger.info("Starting Heroku Session Bot...")
    logger.info("Target app: %s", TARGET_APP_NAME)
    logger.info("Admin chat ID: %s", ADMIN_CHAT_ID)

    app = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("id",      cmd_id))

    # Register error handler
    app.add_error_handler(error_handler)

    logger.info("Bot is running — polling for updates...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # ignore queued messages from offline period
    )


if __name__ == "__main__":
    main()
