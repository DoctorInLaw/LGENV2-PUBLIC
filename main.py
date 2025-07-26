import os
import random
import string
import psycopg2
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID"))
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT")
PORT = int(os.environ.get("PORT", 8080))

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Bot is alive!"

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, channels TEXT, bound_user INTEGER, expiry TEXT, revoked INTEGER)")
cur.execute("CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, channel_id TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS groups (group_name TEXT, alias TEXT)")
conn.commit()

def gen_random_key(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /use <KEY> to unlock your access. 🔑✨")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📞 Contact admin: {ADMIN_CONTACT} ✉️")

async def setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_CONTACT
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /setadmin <username>")
        return
    old = ADMIN_CONTACT
    ADMIN_CONTACT = context.args[0]
    await update.message.reply_text(f"✅ Admin changed from {old} to {ADMIN_CONTACT}")

async def clearkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    cur.execute("DELETE FROM keys WHERE revoked = 1 OR (expiry IS NOT NULL AND expiry < ?)", (datetime.utcnow().isoformat(),))
    conn.commit()
    await update.message.reply_text("🧹 Cleared revoked & expired keys.")

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setgroup <group> <alias1> <alias2>")
        return
    group = context.args[0]
    aliases = context.args[1:]
    for a in aliases:
        cur.execute("INSERT INTO groups VALUES (?, ?)", (group, a))
    conn.commit()
    await update.message.reply_text(f"✅ Group {group} set with {', '.join(aliases)}")

async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = cur.execute("SELECT group_name, alias FROM groups").fetchall()
    out = "".join([f"{g} → {a}\n" for g, a in rows])
    await update.message.reply_text(f"📂 Groups:\n{out}")

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /genkey <alias/group> Xd Yh Xm N OR lifetime")
        return
    input_value = args[0]
    group_rows = cur.execute("SELECT alias FROM groups WHERE group_name = ?", (input_value,)).fetchall()
    if group_rows:
        aliases = [r[0] for r in group_rows]
    else:
        aliases = input_value.split("+")
    channels = []
    for a in aliases:
        cur.execute("SELECT channel_id FROM aliases WHERE alias = ?", (a,))
        row = cur.fetchone()
        channels.append(row[0] if row else a)
    lifetime = "lifetime" in args
    days = hours = minutes = 0
    for arg in args[1:]:
        if arg.endswith("d"): days = int(arg[:-1])
        elif arg.endswith("h"): hours = int(arg[:-1])
        elif arg.endswith("m"): minutes = int(arg[:-1])
    n = int(args[-1]) if args[-1].isdigit() else 1
    keys_created = []
    for _ in range(n):
        k = gen_random_key()
        expiry = None if lifetime else f"{days}d{hours}h{minutes}m"
        cur.execute("INSERT INTO keys VALUES (?, ?, ?, ?, ?)", (k, "+".join(channels), None, expiry, 0))
        keys_created.append(k)
    conn.commit()
    await update.message.reply_text("✅ Generated:\n" + "\n".join(keys_created))

async def usekey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /use <KEY>")
        return
    k = args[0]
    cur.execute("SELECT channels, bound_user, expiry, revoked FROM keys WHERE key = ?", (k,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text(f"❌ Wrong key. Contact {ADMIN_CONTACT}")
        return
    channels, bound_user, expiry, revoked = row
    if revoked:
        await update.message.reply_text(f"⛔ Revoked. Contact {ADMIN_CONTACT}")
        return
    if bound_user and bound_user != user_id:
        await update.message.reply_text(f"🚫 Bound to another user. Contact {ADMIN_CONTACT}")
        return
    if not bound_user:
        bound_user = user_id
        if expiry:
            d = int(expiry.split("d")[0]) if "d" in expiry else 0
            h = int(expiry.split("d")[1].split("h")[0]) if "h" in expiry else 0
            m = int(expiry.split("h")[1].split("m")[0]) if "m" in expiry else 0
            expiry_dt = datetime.utcnow() + timedelta(days=d, hours=h, minutes=m)
        else:
            expiry_dt = None
        cur.execute("UPDATE keys SET bound_user = ?, expiry = ? WHERE key = ?", (user_id, expiry_dt.isoformat() if expiry_dt else None, k))
        conn.commit()
    else:
        expiry_dt = datetime.fromisoformat(expiry) if expiry else None
    if expiry_dt and datetime.utcnow() > expiry_dt:
        await update.message.reply_text(f"⚠️ Expired. Contact {ADMIN_CONTACT}")
        return
    await update.message.reply_text(f"🎉 Access to {len(channels.split('+'))} channels! Sending links...")
    for ch in channels.split("+"):
        link = await context.bot.create_chat_invite_link(chat_id=ch, expire_date=datetime.utcnow() + timedelta(seconds=10), member_limit=1)
        await update.message.reply_text(f"👉 [JOIN]({link.invite_link}) ⚡ 10s", parse_mode="Markdown")
        await asyncio.sleep(10)
        await context.bot.revoke_chat_invite_link(chat_id=ch, invite_link=link.invite_link)
    if expiry_dt:
        days_left = (expiry_dt - datetime.utcnow()).days
        await update.message.reply_text(f"✅ All sent! Valid for {days_left} days. ⏳")
    else:
        await update.message.reply_text("✨✨✨\n🎉 *LIFETIME KEY!* 🎉\n🚀 Unlimited access forever! 🔥\n✨✨✨", parse_mode="Markdown")

async def daily_reminder(app):
    while True:
        now = datetime.utcnow()
        rows = cur.execute("SELECT key, bound_user, expiry FROM keys WHERE expiry IS NOT NULL AND revoked = 0").fetchall()
        for key, user, expiry in rows:
            expiry_dt = datetime.fromisoformat(expiry)
            days_left = (expiry_dt - now).days
            if days_left in [1, 2, 3]:
                await app.bot.send_message(user, f"⏳ Reminder: {days_left} days left. Contact {ADMIN_CONTACT}.")
        await asyncio.sleep(86400)

async def setalias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setalias <alias> <channel_id>")
        return
    cur.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?)", (context.args[0], context.args[1]))
    conn.commit()
    await update.message.reply_text(f"✅ Alias `{context.args[0]}` → `{context.args[1]}`")

async def listaliases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = cur.execute("SELECT * FROM aliases").fetchall()
    out = "\n".join([f"{a} → {c}" for a, c in rows])
    await update.message.reply_text(f"🔖 Aliases:\n{out}")

async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /revoke <KEY>")
        return
    k = context.args[0]
    cur.execute("SELECT bound_user, channels FROM keys WHERE key = ?", (k,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Key not found.")
        return
    bound_user, channels = row
    cur.execute("UPDATE keys SET revoked = 1 WHERE key = ?", (k,))
    conn.commit()
    if bound_user:
        for ch in channels.split("+"):
            await context.bot.ban_chat_member(ch, bound_user)
            await context.bot.unban_chat_member(ch, bound_user)
        await context.bot.send_message(bound_user, "⛔ Revoked and removed.")
    await update.message.reply_text(f"✅ Revoked {k}")

async def revokeall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = cur.execute("SELECT key, bound_user, channels FROM keys WHERE revoked = 0").fetchall()
    for k, bound_user, channels in rows:
        cur.execute("UPDATE keys SET revoked = 1 WHERE key = ?", (k,))
        if bound_user:
            for ch in channels.split("+"):
                await context.bot.ban_chat_member(ch, bound_user)
                await context.bot.unban_chat_member(ch, bound_user)
            await context.bot.send_message(bound_user, "⚠️ Revoked by admin.")
    conn.commit()
    await update.message.reply_text("✅ All keys revoked.")

async def listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = cur.execute("SELECT key, bound_user, expiry, revoked FROM keys").fetchall()
    out = "🔑 All keys:\n"
    for key, bound_user, expiry, revoked in rows:
        status = "❌ Revoked" if revoked else "✅ Active"
        username = "-"
        if bound_user:
            try:
                user = await context.bot.get_chat(bound_user)
                username = user.username or "-"
            except:
                pass
        left = "-"
        if expiry and not revoked:
            dt = datetime.fromisoformat(expiry)
            left = str(dt - datetime.utcnow()).split(".")[0]
        out += f"[`{key}`] [{left}] [{username}] [{bound_user}] {status}\n"
    await update.message.reply_text(out, parse_mode="Markdown")

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def run_bot():
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("contact", contact))
    app_.add_handler(CommandHandler("setadmin", setadmin))
    app_.add_handler(CommandHandler("clearkeys", clearkeys))
    app_.add_handler(CommandHandler("setgroup", setgroup))
    app_.add_handler(CommandHandler("listgroups", listgroups))
    app_.add_handler(CommandHandler("genkey", genkey))
    app_.add_handler(CommandHandler("use", usekey))
    app_.add_handler(CommandHandler("setalias", setalias))
    app_.add_handler(CommandHandler("listaliases", listaliases))
    app_.add_handler(CommandHandler("revoke", revoke))
    app_.add_handler(CommandHandler("revokeall", revokeall))
    app_.add_handler(CommandHandler("listkeys", listkeys))

    async def post_init(app_):
        app_.create_task(daily_reminder(app_))

    app_.post_init = post_init
    app_.run_polling()

if __name__ == "__main__":
    Thread(target=run_flask).start()
    run_bot()
