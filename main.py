import asyncio
import json
import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BACKUP_DATA_FILE = "backups.json"


def load_backups():
    if os.path.exists(BACKUP_DATA_FILE):
        with open(BACKUP_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_backups(backups):
    with open(BACKUP_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(backups, f, ensure_ascii=False, indent=2)


backups = load_backups()


def get_main_menu(user_id):
    """Main menu keyboard"""
    files_count = len(backups.get(user_id, []))
    keyboard = [
        [InlineKeyboardButton(f"📦 Files ({files_count})", callback_data="menu_files")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="menu_info")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_text(user_id):
    """Main menu text"""
    files_count = len(backups.get(user_id, []))
    total_size = sum(f["file_size"] for f in backups.get(user_id, []))

    return (
        "╔═══════════════════╗\n"
        "║   BACKUP VAULT   ║\n"
        "╚═══════════════════╝\n\n"
        f"Files: {files_count}\n"
        f"Size: {format_size(total_size)}\n"
        f"Status: Active\n\n"
        "Send file to backup"
    )


def get_files_menu(user_id, page=0):
    """Files list with pagination"""
    if user_id not in backups or not backups[user_id]:
        keyboard = [[InlineKeyboardButton("« Main", callback_data="menu_main")]]
        return InlineKeyboardMarkup(keyboard), "No files yet\nSend a file to start"

    files = backups[user_id]
    per_page = 6
    total_pages = (len(files) - 1) // per_page + 1
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(files))

    keyboard = []

    for i in range(start_idx, end_idx):
        backup = files[i]
        icon = get_file_icon(backup["mime_type"])
        name = (
            backup["description"][:20] + "..."
            if len(backup["description"]) > 20
            else backup["description"]
        )
        size = format_size(backup["file_size"])
        keyboard.append(
            [InlineKeyboardButton(f"{icon} {name} • {size}", callback_data=f"file_{i}")]
        )

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("‹", callback_data=f"page_{page - 1}"))
    nav_row.append(
        InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("›", callback_data=f"page_{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append(
        [
            InlineKeyboardButton("🗑 Clear", callback_data="confirm_clear"),
            InlineKeyboardButton("« Main", callback_data="menu_main"),
        ]
    )

    text = f"📦 YOUR FILES\n\nTotal: {len(files)} files"
    return InlineKeyboardMarkup(keyboard), text


def get_file_icon(mime_type):
    if not mime_type:
        return "📄"
    if "image" in mime_type:
        return "🖼"
    if "video" in mime_type:
        return "🎬"
    if "audio" in mime_type:
        return "🎵"
    if "pdf" in mime_type:
        return "📕"
    if "zip" in mime_type or "rar" in mime_type:
        return "📦"
    if "text" in mime_type:
        return "📝"
    return "📄"


def format_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


async def delete_message_after_delay(context, chat_id, message_id, delay=20):
    """Delete message after delay"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = str(update.message.from_user.id)

    msg = await update.message.reply_text(
        get_main_text(user_id), reply_markup=get_main_menu(user_id)
    )

    context.user_data["main_message_id"] = msg.message_id


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming files"""
    user_id = str(update.message.from_user.id)
    file = update.message.document

    # Delete user's file message
    try:
        await update.message.delete()
    except:
        pass

    context.user_data["pending_file"] = {
        "file_id": file.file_id,
        "file_name": file.file_name,
        "file_size": file.file_size,
        "mime_type": file.mime_type,
    }

    icon = get_file_icon(file.mime_type)
    text = (
        f"{icon} NEW FILE\n\n"
        f"Name: {file.file_name}\n"
        f"Size: {format_size(file.file_size)}\n\n"
        f"Send description below:"
    )

    keyboard = [[InlineKeyboardButton("✖ Cancel", callback_data="cancel_upload")]]

    # Try to edit existing main message, or create new one
    if "main_message_id" in context.user_data:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data["main_message_id"],
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        except:
            pass

    msg = await update.effective_chat.send_message(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["main_message_id"] = msg.message_id


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (descriptions)"""
    user_id = str(update.message.from_user.id)

    # Delete user's text message
    try:
        await update.message.delete()
    except:
        pass

    if "pending_file" not in context.user_data:
        return

    file_info = context.user_data["pending_file"]
    description = update.message.text

    if user_id not in backups:
        backups[user_id] = []

    backup_entry = {
        "file_id": file_info["file_id"],
        "file_name": file_info["file_name"],
        "file_size": file_info["file_size"],
        "mime_type": file_info["mime_type"],
        "description": description,
        "timestamp": datetime.now().isoformat(),
    }

    backups[user_id].append(backup_entry)
    save_backups(backups)
    del context.user_data["pending_file"]

    icon = get_file_icon(file_info["mime_type"])
    text = (
        f"✓ SAVED\n\n"
        f"{icon} {description}\n"
        f"Size: {format_size(file_info['file_size'])}\n\n"
        f"Total files: {len(backups[user_id])}"
    )

    keyboard = [[InlineKeyboardButton("View Files", callback_data="menu_files")]]
    keyboard.append([InlineKeyboardButton("« Main", callback_data="menu_main")])

    if "main_message_id" in context.user_data:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data["main_message_id"],
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except:
            msg = await update.effective_chat.send_message(
                text, reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["main_message_id"] = msg.message_id


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    data = query.data

    if data == "menu_main":
        await query.edit_message_text(
            get_main_text(user_id), reply_markup=get_main_menu(user_id)
        )

    elif data == "menu_files":
        context.user_data["current_page"] = 0
        keyboard, text = get_files_menu(user_id, 0)
        await query.edit_message_text(text, reply_markup=keyboard)

    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        context.user_data["current_page"] = page
        keyboard, text = get_files_menu(user_id, page)
        await query.edit_message_text(text, reply_markup=keyboard)

    elif data.startswith("file_"):
        idx = int(data.split("_")[1])

        if user_id not in backups or idx >= len(backups[user_id]):
            await query.answer("File not found", show_alert=True)
            return

        backup = backups[user_id][idx]
        icon = get_file_icon(backup["mime_type"])

        # Send file separately
        file_msg = await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=backup["file_id"],
            caption=f"{icon} {backup['description']}",
        )

        # Schedule deletion
        asyncio.create_task(
            delete_message_after_delay(
                context, query.message.chat_id, file_msg.message_id, 20
            )
        )

        # Show details
        text = (
            f"{icon} FILE INFO\n\n"
            f"Name: {backup['file_name']}\n"
            f"Description: {backup['description']}\n"
            f"Size: {format_size(backup['file_size'])}\n"
            f"Date: {backup['timestamp'][:10]}\n\n"
            f"⏱ File will auto-delete in 20s"
        )

        keyboard = [
            [InlineKeyboardButton("🗑 Delete", callback_data=f"del_{idx}")],
            [InlineKeyboardButton("« Files", callback_data="menu_files")],
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("del_"):
        idx = int(data.split("_")[1])

        if user_id not in backups or idx >= len(backups[user_id]):
            await query.answer("File not found", show_alert=True)
            return

        deleted = backups[user_id].pop(idx)
        save_backups(backups)

        text = f"✓ DELETED\n\n{deleted['description']}"
        keyboard = [[InlineKeyboardButton("« Files", callback_data="menu_files")]]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "confirm_clear":
        keyboard = [
            [InlineKeyboardButton("⚠️ Yes, Delete All", callback_data="clear_all")],
            [InlineKeyboardButton("✖ Cancel", callback_data="menu_files")],
        ]
        text = "⚠️ WARNING\n\nDelete all files?\nCannot be undone"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "clear_all":
        count = len(backups.get(user_id, []))
        backups[user_id] = []
        save_backups(backups)

        text = f"✓ CLEARED\n\nDeleted {count} files"
        keyboard = [[InlineKeyboardButton("« Main", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "cancel_upload":
        if "pending_file" in context.user_data:
            del context.user_data["pending_file"]
        await query.edit_message_text(
            get_main_text(user_id), reply_markup=get_main_menu(user_id)
        )

    elif data == "menu_info":
        files_count = len(backups.get(user_id, []))
        total_size = sum(f["file_size"] for f in backups.get(user_id, []))

        text = (
            "ℹ️ INFO\n\n"
            f"Total files: {files_count}\n"
            f"Total size: {format_size(total_size)}\n\n"
            "Commands:\n"
            "/start - Main menu\n"
            "/files - Quick access"
        )
        keyboard = [[InlineKeyboardButton("« Main", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "noop":
        pass


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick access to files"""
    user_id = str(update.message.from_user.id)
    keyboard, text = get_files_menu(user_id, 0)

    msg = await update.message.reply_text(text, reply_markup=keyboard)
    context.user_data["main_message_id"] = msg.message_id


def main():
    """Start the bot"""
    TOKEN = "8208249842:AAEca1Ps3HVcz6NlEIbW_JPWD479XhvJRkQ"

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_handler(CallbackQueryHandler(button_callback))

    print("BOT ONLINE")
    application.run_polling()


if __name__ == "__main__":
    main()
