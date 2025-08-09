import logging
import sqlite3
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters
)
from telegram.request import HTTPXRequest
import os  # For reading environment variables

# Read the bot token from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = None  # Add proxy URL here if needed, e.g., "socks5://127.0.0.1:1080"

# Conversation states
ENTER_TASK, ENTER_TIME, EDIT_SELECT, EDIT_TASK, EDIT_TIME = range(5)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

main_menu_keyboard = ReplyKeyboardMarkup(
    [["Add Task", "List Task"]],
    resize_keyboard=True
)

edit_menu_keyboard = ReplyKeyboardMarkup(
    [["Edit Task", "Back"]],
    resize_keyboard=True
)

def init_db():
    """Initialize the SQLite database and create tasks table if not exists."""
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            task TEXT,
            time TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_task_db(user_id: str, task: str, time: str):
    """Add a new task to the database."""
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('INSERT INTO tasks (user_id, task, time) VALUES (?, ?, ?)', (user_id, task, time))
    conn.commit()
    conn.close()

def get_tasks_db(user_id: str):
    """Retrieve all tasks for a given user."""
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('SELECT id, task, time FROM tasks WHERE user_id = ?', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_task_db(task_id: int, new_task: str, new_time: str):
    """Update a task's description and time by its ID."""
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('UPDATE tasks SET task = ?, time = ? WHERE id = ?', (new_task, new_time, task_id))
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and show main menu keyboard."""
    await update.message.reply_text(
        "Welcome! Use the keyboard below to manage your tasks.",
        reply_markup=main_menu_keyboard
    )
    return ConversationHandler.END

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu commands from user."""
    text = update.message.text
    user_id = str(update.message.from_user.id)

    if text == "Add Task":
        await update.message.reply_text("Please enter the task description:", reply_markup=ReplyKeyboardRemove())
        return ENTER_TASK

    elif text == "List Task":
        tasks = get_tasks_db(user_id)
        if not tasks:
            await update.message.reply_text("You have no tasks.", reply_markup=main_menu_keyboard)
            return ConversationHandler.END

        message_text = "Your tasks:\n"
        for idx, (tid, task, time_str) in enumerate(tasks, start=1):
            message_text += f"{idx}. {task} at {time_str} (ID: {tid})\n"

        await update.message.reply_text(message_text, reply_markup=edit_menu_keyboard)
        return ConversationHandler.END

    elif text == "Edit Task":
        await update.message.reply_text("Please enter the ID of the task you want to edit:", reply_markup=ReplyKeyboardRemove())
        return EDIT_SELECT

    elif text == "Back":
        await update.message.reply_text("Back to main menu.", reply_markup=main_menu_keyboard)
        return ConversationHandler.END

    elif text == "Cancel":
        await update.message.reply_text("Operation cancelled.", reply_markup=main_menu_keyboard)
        return ConversationHandler.END

    else:
        await update.message.reply_text("Please use the keyboard below.", reply_markup=main_menu_keyboard)
        return ConversationHandler.END

async def enter_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the task description and ask for the reminder time."""
    context.user_data['task'] = update.message.text
    await update.message.reply_text("Please enter the time for reminder (HH:MM):")
    return ENTER_TIME

async def enter_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the reminder time and add the task to the database."""
    user_id = str(update.message.from_user.id)
    time_str = update.message.text
    try:
        datetime.strptime(time_str, '%H:%M')
        add_task_db(user_id, context.user_data['task'], time_str)
        await update.message.reply_text(f"Task '{context.user_data['task']}' added for {time_str}.", reply_markup=main_menu_keyboard)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Invalid time format! Please use HH:MM.")
        return ENTER_TIME

async def edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get task ID from user for editing."""
    user_id = str(update.message.from_user.id)
    try:
        task_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid ID. Please enter a numeric task ID:")
        return EDIT_SELECT

    tasks = get_tasks_db(user_id)
    task_ids = [tid for tid, _, _ in tasks]
    if task_id not in task_ids:
        await update.message.reply_text("Task ID not found. Please enter a valid ID:")
        return EDIT_SELECT

    context.user_data['edit_task_id'] = task_id
    await update.message.reply_text("Enter the new task description:")
    return EDIT_TASK

async def edit_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new task description and ask for new time."""
    context.user_data['edit_task_desc'] = update.message.text
    await update.message.reply_text("Enter the new time for the task (HH:MM):")
    return EDIT_TIME

async def edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the new time and update the task in the database."""
    time_str = update.message.text
    try:
        datetime.strptime(time_str, '%H:%M')
    except ValueError:
        await update.message.reply_text("Invalid time format! Please use HH:MM:")
        return EDIT_TIME

    task_id = context.user_data.get('edit_task_id')
    if not task_id:
        await update.message.reply_text("Unexpected error. Please try again.", reply_markup=main_menu_keyboard)
        return ConversationHandler.END

    update_task_db(task_id, context.user_data['edit_task_desc'], time_str)
    await update.message.reply_text("Task updated successfully!", reply_markup=main_menu_keyboard)
    return ConversationHandler.END

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Periodically check for tasks matching the current time and send reminders."""
    now = datetime.now().strftime('%H:%M')
    conn = sqlite3.connect('tasks.db')
    c = conn.cursor()
    c.execute('SELECT id, user_id, task, time FROM tasks')
    rows = c.fetchall()

    for task_id, user_id, task, time_str in rows:
        if time_str == now:
            try:
                await context.bot.send_message(chat_id=int(user_id), text=f"Reminder: {task}")
            except Exception as e:
                logging.error(f"Failed to send reminder to {user_id}: {e}")
            c.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation and show main menu."""
    await update.message.reply_text("Operation cancelled.", reply_markup=main_menu_keyboard)
    return ConversationHandler.END

def main():
    """Initialize database, set up handlers, and start the bot."""
    init_db()
    request = HTTPXRequest(proxy_url=PROXY_URL) if PROXY_URL else None
    app = Application.builder().token(BOT_TOKEN).request(request).build() if request else Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(Add Task|List Task|Edit Task|Back|Cancel)$"), handle_main_menu)
        ],
        states={
            ENTER_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_task)],
            ENTER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_time)],
            EDIT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_select)],
            EDIT_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_task)],
            EDIT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(conv_handler)

    app.job_queue.run_repeating(check_reminders, interval=60, first=0)

    app.run_polling()

if __name__ == '__main__':
    main()

