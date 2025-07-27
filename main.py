# file: main.py
# ✅ Final full Telegram bot with all features discussed

import os
import csv
import io
import string
import random
import psycopg2
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes,
import telegram
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID"))
LOCKED = False
ADMINS = {ADMIN_ID}
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))

app = Flask(__name__)
bot = Bot(BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()
dispatcher: Dispatcher = application.dispatcher

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, channels TEXT, bound_user INTEGER, expiry TEXT, revoked INTEGER)")
cur.execute("CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, channel_id TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS groups (group_name TEXT, alias TEXT)")
conn.commit()

def gen_random_key(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def parse_duration(s):
    if s.lower() in ("l", "lifetime"):
        return None
    days = hours = 0
    if "d" in s:
        parts = s.split("d")
        days = int(parts[0])
        s = parts[1] if len(parts) > 1 else ""
    if "h" in s:
        parts = s.split("h")
        hours = int(parts[0])
    return timedelta(days=days, hours=hours)

@app.route("/")
def home():
    return "✅ Bot is alive!"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    asyncio.run(dispatcher.process_update(update))
    return "OK"

# === USER COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
    "👋 *Welcome to the Link Gen V2 Bot!*\n"
    "🔑 Unlock your premium perks using a secret key: `/use <KEY>`\n"
    "🧠 Need help? Type `/help` to see what I can do.\n\n"
    "💎 *This is not just another bot — it's your gateway to premium content.*",
    parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
    "📘 *Command Menu* — _Everything you can do here_\n\n"
    "👤 *User Commands*\n"
    "`/start` — Welcome message\n"
    "`/use <KEY>` — Redeem your key and unlock channels\n"
    "`/mykey` — View your active key and access\n"
    "`/contact` — Reach the admin\n\n"
    "🔐 *Admin Panel*\n"
    "`/genkey`, `/revoke`, `/revokeall`, `/extend`, `/extendall`\n"
    "`/clearkeys`, `/keyinfo`, `/listkeys`, `/exportkeys`\n"
    "`/setalias`, `/deletealias`, `/listaliases`\n"
    "`/setgroup`, `/listgroups`\n"
    "`/remind3`, `/broadcast`, `/setadmin`",
    parse_mode="Markdown"
)

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
    f"📞 *Need help?*\nReach out to the admin directly: [@{ADMIN_CONTACT}](https://t.me/{ADMIN_CONTACT})",
    parse_mode="Markdown"
)

async def mykey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT key, expiry, channels, revoked FROM keys WHERE bound_user = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("🔍 You have no active key.")
        return
    key, expiry, channels, revoked = row
    status = "❌ Revoked" if revoked else "✅ Active"
    expiry_display = expiry or "💎 Lifetime"
    await update.message.reply_text(
    f"🧾 *Your Key Summary*\n\n"
    f"🔑 Key: `{key}`\n"
    f"📺 Channels: `{channels}`\n"
    f"📅 Expiry: `{expiry or '💎 Lifetime Access'}`\n"
    f"📌 Status: `{status}`\n\n"
    f"✨ Stay premium, stay ahead!",
    parse_mode="Markdown"
)

# === EXTEND / REMIND / BROADCAST ===
async def extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /extend <KEY> <1d2h or L>")
        return
    k, dur = context.args
    td = parse_duration(dur)
    expiry = (datetime.utcnow() + td).isoformat() if td else None
    cur.execute("UPDATE keys SET expiry = %s WHERE key = %s", (expiry, k))
    conn.commit()
    cur.execute("SELECT bound_user FROM keys WHERE key = %s", (k,))
    row = cur.fetchone()
    if row and row[0]:
        await context.bot.send_message(row[0], f"⏳ Your key `{k}` has been extended. New expiry: {expiry or '💎 Lifetime'}", parse_mode="Markdown")
    await update.message.reply_text("✅ Key expiry updated.")

async def extendall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /extendall <1d2h or L>")
        return
    dur = context.args[0]
    td = parse_duration(dur)
    expiry = (datetime.utcnow() + td).isoformat() if td else None
    cur.execute("SELECT key, bound_user FROM keys WHERE revoked = 0")
    for k, u in cur.fetchall():
        cur.execute("UPDATE keys SET expiry = %s WHERE key = %s", (expiry, k))
        if u:
            try:
                await context.bot.send_message(u, f"🕓 Your access key `{k}` was extended.\nNew expiry: {expiry or '💎 Lifetime'}", parse_mode="Markdown")
            except: pass
    conn.commit()
    await update.message.reply_text("✅ All keys extended.")

async def remind3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    now = datetime.utcnow()
    cur.execute("SELECT key, bound_user, expiry, channels FROM keys WHERE expiry IS NOT NULL AND revoked = 0")
    count = 0
    for k, uid, exp, ch in cur.fetchall():
        dt = datetime.fromisoformat(exp)
        if 0 <= (dt - now).days <= 3:
            try:
                await context.bot.send_message(uid,
                    f"🔔 *Access Expiring Soon!*\n"
                    f"Your key `{k}` will expire on `{dt.strftime('%Y-%m-%d %H:%M')}` UTC.\n"
                    f"Channels: {ch}\nPlease renew soon to avoid losing access.",
                    parse_mode="Markdown")
                count += 1
            except: pass
    await update.message.reply_text(f"✅ {count} reminders sent.")
# === KEY REDEMPTION ===
async def use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if LOCKED and user_id not in ADMINS:
    await update.message.reply_text("🔒 The bot is currently under maintenance. Try again later.")
    return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /use <KEY>")
        return
    k = context.args[0]
    cur.execute("SELECT channels, bound_user, expiry, revoked FROM keys WHERE key = %s", (k,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text(f"❌ Invalid key. Contact @{ADMIN_CONTACT}")
        return
    channels, bound_user, expiry, revoked = row
    if revoked:
        await update.message.reply_text(f"🚫 This key has been revoked. Contact @{ADMIN_CONTACT}")
        return
    if bound_user and bound_user != user_id:
        await update.message.reply_text(f"🔒 Key already bound to another user. Contact @{ADMIN_CONTACT}")
        return

    if not bound_user:
        expiry_dt = datetime.utcnow() + parse_duration(expiry) if expiry else None
        cur.execute("UPDATE keys SET bound_user = %s, expiry = %s WHERE key = %s",
                    (user_id, expiry_dt.isoformat() if expiry_dt else None, k))
        conn.commit()
    else:
        expiry_dt = datetime.fromisoformat(expiry) if expiry else None

    if expiry_dt and datetime.utcnow() > expiry_dt:
    for ch in channels.split("+"):
        try:
            await context.bot.ban_chat_member(ch, user_id)
            await context.bot.unban_chat_member(ch, user_id)
        except: pass
    await update.message.reply_text("⏳ Your key has expired. Access removed from all channels. Please contact admin.")
    return


    ch_list = channels.split("+")
    for ch in ch_list:
        try:
            link = await context.bot.create_chat_invite_link(chat_id=ch, expire_date=datetime.utcnow() + timedelta(seconds=15), member_limit=1)
            await update.message.reply_text(f"👉 [Join Channel]({link.invite_link})", parse_mode="Markdown")
            await asyncio.sleep(10)
            await context.bot.revoke_chat_invite_link(chat_id=ch, invite_link=link.invite_link)
        except:
            await update.message.reply_text(f"⚠️ Failed to generate invite for {ch}")

    if not expiry:
        await update.message.reply_text(
             "```\n"
    "╔══════════════════════════════════════╗\n"
    "║   🎉 LIFETIME ACCESS UNLOCKED! 🎉    ║\n"
    "╠══════════════════════════════════════╣\n"
    "║ 💎 You now have UNLIMITED access     ║\n"
    "║    to all premium channels.          ║\n"
    "║ 🚀 No expiry. No limits. Forever.    ║\n"
    "╠══════════════════════════════════════╣\n"
    "║ 🏆 Welcome to the Elite Circle.      ║\n"
    "║ ✨ You’re officially one of us. ✨   ║\n"
    "╚══════════════════════════════════════╝\n"
    "```",
            parse_mode="Markdown")
    else:
        days_left = (expiry_dt - datetime.utcnow()).days
        await update.message.reply_text(f"✅ Access granted! Your key is valid for *{days_left}* more day(s).", parse_mode="Markdown")

# === ADMIN COMMANDS ===
async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /genkey <alias/group> <1d2h/L> [count]")
        return
    input_value, duration = context.args[0], context.args[1]
    count = int(context.args[2]) if len(context.args) == 3 else 1

    group_rows = cur.execute("SELECT alias FROM groups WHERE group_name = %s", (input_value,)); aliases = [r[0] for r in group_rows.fetchall()] if group_rows else input_value.split("+")
    channels = []
    for a in aliases:
        cur.execute("SELECT channel_id FROM aliases WHERE alias = %s", (a,))
        row = cur.fetchone()
        channels.append(row[0] if row else a)

    keys_created = []
    expiry = None if duration.lower() in ("l", "lifetime") else duration
    for _ in range(count):
        key = gen_random_key()
        cur.execute("INSERT INTO keys VALUES (%s, %s, %s, %s, %s)",
                    (key, "+".join(channels), None, expiry, 0))
        keys_created.append(key)
    conn.commit()
    await update.message.reply_text("✅ Generated keys:\n" + "\n".join(keys_created))

async def setalias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setalias <alias> <channel_id>")
        return
    cur.execute("INSERT INTO aliases VALUES (%s, %s) ON CONFLICT(alias) DO UPDATE SET channel_id = EXCLUDED.channel_id", (context.args[0], context.args[1]))
    conn.commit()
    await update.message.reply_text(f"✅ Alias `{context.args[0]}` → `{context.args[1]}`", parse_mode="Markdown")

async def deletealias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /deletealias <alias>")
        return
    cur.execute("DELETE FROM aliases WHERE alias = %s", (context.args[0],))
    conn.commit()
    await update.message.reply_text("🗑️ Alias deleted.")

async def listaliases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT * FROM aliases")
    aliases = cur.fetchall()
    out = "\n".join([f"{a} → {c}" for a, c in aliases])
    await update.message.reply_text(f"📌 Aliases:\n{out}")

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setgroup <group> <alias1> <alias2>")
        return
    group = context.args[0]
    cur.execute("DELETE FROM groups WHERE group_name = %s", (group,))
    for a in context.args[1:]:
        cur.execute("INSERT INTO groups VALUES (%s, %s)", (group, a))
    conn.commit()
    await update.message.reply_text(f"✅ Group `{group}` updated.", parse_mode="Markdown")

async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT group_name, alias FROM groups")
    out = ""
    for g, a in cur.fetchall():
        out += f"{g} → {a}\n"
    await update.message.reply_text(f"📂 Groups:\n{out}")

async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /revoke <KEY>")
        return
    k = context.args[0]
    cur.execute("SELECT bound_user, channels FROM keys WHERE key = %s", (k,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("❌ Key not found.")
        return
    bound_user, channels = row
    cur.execute("UPDATE keys SET revoked = 1 WHERE key = %s", (k,))
    conn.commit()
    if bound_user:
        for ch in channels.split("+"):
            try:
                await context.bot.ban_chat_member(ch, bound_user)
                await context.bot.unban_chat_member(ch, bound_user)
            except: pass
    await update.message.reply_text("🔒 Key revoked and user removed from channels.")


async def revokeall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT key, bound_user, channels FROM keys WHERE revoked = 0")
    for k, bound_user, channels in cur.fetchall():
        cur.execute("UPDATE keys SET revoked = 1 WHERE key = %s", (k,))
        if bound_user:
            for ch in channels.split("+"):
                try:
                    await context.bot.ban_chat_member(ch, bound_user)
                    await context.bot.unban_chat_member(ch, bound_user)
                except: pass
    conn.commit()
    await update.message.reply_text("🔐 All keys revoked and users removed from channels.")


async def keyinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /keyinfo <KEY>")
        return
    k = context.args[0]
    cur.execute("SELECT * FROM keys WHERE key = %s", (k,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("❌ Not found.")
        return
    await update.message.reply_text(f"🔑 Key Info:\n{row}")

async def clearkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    now = datetime.utcnow().isoformat()
    cur.execute("DELETE FROM keys WHERE revoked = 1 OR (expiry IS NOT NULL AND expiry < %s)", (now,))
    conn.commit()
    await update.message.reply_text("🧹 Cleared expired/revoked keys.")

async def listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT key, bound_user, expiry, revoked FROM keys")
    out = "🔑 All Keys:\n"
    for k, uid, exp, r in cur.fetchall():
        status = "❌ Revoked" if r else "✅ Active"
        out += f"{k} → {uid} | {exp or 'Lifetime'} | {status}\n"
    await update.message.reply_text(out)

async def exportkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT * FROM keys")
    data = cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Key', 'Channels', 'User', 'Expiry', 'Revoked'])
    writer.writerows(data)
    output.seek(0)
    await update.message.reply_document(document=output.getvalue(), filename="keys.csv")

async def setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_CONTACT
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /setadmin <username>")
        return
    ADMIN_CONTACT = context.args[0]
    await update.message.reply_text("✅ Admin contact updated.")

async def purgeexpired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    now = datetime.utcnow()
    cur.execute("SELECT key, bound_user, channels, expiry FROM keys WHERE expiry IS NOT NULL AND revoked = 0")
    expired = 0

    for k, user_id, ch_str, expiry in cur.fetchall():
        expiry_dt = datetime.fromisoformat(expiry)
        if now > expiry_dt:
            if user_id:
                for ch in ch_str.split("+"):
                    try:
                        await context.bot.ban_chat_member(ch, user_id)
                        await context.bot.unban_chat_member(ch, user_id)
                    except:
                        pass
            cur.execute("UPDATE keys SET revoked = 1 WHERE key = %s", (k,))
            expired += 1

    conn.commit()
    await update.message.reply_text(f"🧹 {expired} expired keys processed.\n👤 Bound users removed from channels.")

# === ADMIN EXTENSIONS ===

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    cur.execute("SELECT COUNT(*) FROM keys"); total_keys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM keys WHERE revoked = 0"); active_keys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM keys WHERE revoked = 1"); revoked_keys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT bound_user) FROM keys WHERE bound_user IS NOT NULL"); users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM aliases"); alias_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT group_name) FROM groups"); group_count = cur.fetchone()[0]

    await update.message.reply_text(
        f"📊 *Bot Stats*\n\n"
        f"🔑 Total Keys: {total_keys}\n"
        f"✅ Active Keys: {active_keys}\n"
        f"❌ Revoked Keys: {revoked_keys}\n"
        f"👥 Unique Users: {users}\n"
        f"🏷️ Aliases: {alias_count}\n"
        f"🗂️ Groups: {group_count}",
        parse_mode="Markdown")

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    buffer = io.BytesIO()
    zip_writer = csv.writer(buffer)

    cur.execute("SELECT * FROM keys")
    keys_data = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Key', 'Channels', 'User', 'Expiry', 'Revoked'])
    writer.writerows(keys_data)
    output.seek(0)

    await update.message.reply_document(document=output.getvalue(), filename="keys_backup.csv")

async def migratealias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /migratealias <old> <new>")
        return
    old, new = context.args
    cur.execute("UPDATE aliases SET channel_id = %s WHERE alias = %s", (new, old))
    cur.execute("UPDATE groups SET alias = %s WHERE alias = %s", (new, old))
    conn.commit()
    await update.message.reply_text(f"🔁 Alias `{old}` migrated to `{new}`", parse_mode="Markdown")

async def whohas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /whohas <alias/group>")
        return
    target = context.args[0]
    cur.execute("SELECT alias FROM groups WHERE group_name = %s", (target,))
    group_rows = cur.fetchall()
    aliases = [target] if not group_rows else [r[0] for r in group_rows]

    cur.execute("SELECT key, bound_user FROM keys")
    out = ""
    for k, uid in cur.fetchall():
        cur.execute("SELECT channels FROM keys WHERE key = %s", (k,))
        ch = cur.fetchone()[0].split("+")
        if any(a in ch for a in aliases):
            out += f"{k} → {uid}\n"
    await update.message.reply_text(out or "No users found.")

async def renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /renew <KEY> <1d2h or L>")
        return
    k, duration = context.args
    cur.execute("SELECT key FROM keys WHERE key = %s", (k,))
    if not cur.fetchone():
        await update.message.reply_text("❌ Key does not exist. Cannot renew.")
        return
    td = parse_duration(duration)
    expiry = (datetime.utcnow() + td).isoformat() if td else None
    cur.execute("UPDATE keys SET expiry = %s WHERE key = %s", (expiry, k))
    conn.commit()
    await update.message.reply_text("🔁 Key renewed successfully.")

async def renewall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /renewall <1d2h or L>")
        return
    dur = context.args[0]
    td = parse_duration(dur)
    expiry = (datetime.utcnow() + td).isoformat() if td else None
    cur.execute("UPDATE keys SET expiry = %s WHERE revoked = 0", (expiry,))
    conn.commit()
    await update.message.reply_text(f"🔁 All active keys renewed with expiry: `{expiry or 'Lifetime'}`", parse_mode="Markdown")

async def addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addkey <CUSTOM_KEY> <1d2h or L> <alias1+alias2+...>")
        return
    custom_key = context.args[0]
    duration = context.args[1]
    aliases = context.args[2] if len(context.args) > 2 else ""
    td = parse_duration(duration)
    expiry = (datetime.utcnow() + td).isoformat() if td else None
    cur.execute("INSERT INTO keys VALUES (%s, %s, %s, %s, %s)", (custom_key, aliases, None, expiry, 0))
    conn.commit()
    await update.message.reply_text(f"✅ Custom key `{custom_key}` created.", parse_mode="Markdown")

async def resetbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("⚠️ Are you sure you want to reset the bot? Type `/confirmreset` to proceed.")

async def confirmreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    # Export everything
    tables = ['keys', 'aliases', 'groups']
    for table in tables:
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        if table == 'keys':
            writer.writerow(['Key', 'Channels', 'BoundUser', 'Expiry', 'Revoked'])
        elif table == 'aliases':
            writer.writerow(['Alias', 'Channel ID'])
        elif table == 'groups':
            writer.writerow(['Group Name', 'Alias'])
        writer.writerows(rows)
        output.seek(0)
        await update.message.reply_document(document=output.getvalue(), filename=f"{table}_backup.csv")
    
    # Clear all data
    for table in tables:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    await update.message.reply_text("🧨 Bot reset completed. All data wiped.")

# Multi-admin support
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    uid = int(context.args[0])
    ADMINS.add(uid)
    await update.message.reply_text(f"✅ User `{uid}` added to admin list.", parse_mode="Markdown")

async def rmadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /rmadmin <user_id>")
        return
    uid = int(context.args[0])
    if uid == ADMIN_ID:
        await update.message.reply_text("❌ Cannot remove the root admin.")
        return
    ADMINS.discard(uid)
    await update.message.reply_text(f"🗑️ User `{uid}` removed from admins.", parse_mode="Markdown")

async def admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    out = "\n".join([f"👑 {uid}" for uid in ADMINS])
    await update.message.reply_text(f"📋 *Current Admins:*\n{out}", parse_mode="Markdown")

# Lock/Unlock
async def lockbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LOCKED
    if update.effective_user.id not in ADMINS: return
    LOCKED = True
    await update.message.reply_text("🚫 Bot is now LOCKED. Users cannot use /use command.")

async def unlockbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LOCKED
    if update.effective_user.id not in ADMINS: return
    LOCKED = False
    await update.message.reply_text("✅ Bot is now UNLOCKED. Users can redeem keys again.")

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS: return
    msg = "🚧 We’re performing maintenance. Some features may be unavailable temporarily."
    if context.args:
        msg += "\n" + " ".join(context.args)
    cur.execute("SELECT DISTINCT bound_user FROM keys WHERE bound_user IS NOT NULL")
    for row in cur.fetchall():
        try:
            await context.bot.send_message(row[0], msg)
        except: pass
    await update.message.reply_text("📢 Maintenance message sent to all users.")





# === REGISTER HANDLERS ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_cmd))
dispatcher.add_handler(CommandHandler("contact", contact))
dispatcher.add_handler(CommandHandler("mykey", mykey))
dispatcher.add_handler(CommandHandler("use", use))
dispatcher.add_handler(CommandHandler("genkey", genkey))
dispatcher.add_handler(CommandHandler("extend", extend))
dispatcher.add_handler(CommandHandler("extendall", extendall))
dispatcher.add_handler(CommandHandler("broadcast", broadcast))
dispatcher.add_handler(CommandHandler("remind3", remind3))
dispatcher.add_handler(CommandHandler("setalias", setalias))
dispatcher.add_handler(CommandHandler("deletealias", deletealias))
dispatcher.add_handler(CommandHandler("listaliases", listaliases))
dispatcher.add_handler(CommandHandler("setgroup", setgroup))
dispatcher.add_handler(CommandHandler("listgroups", listgroups))
dispatcher.add_handler(CommandHandler("revoke", revoke))
dispatcher.add_handler(CommandHandler("revokeall", revokeall))
dispatcher.add_handler(CommandHandler("keyinfo", keyinfo))
dispatcher.add_handler(CommandHandler("clearkeys", clearkeys))
dispatcher.add_handler(CommandHandler("listkeys", listkeys))
dispatcher.add_handler(CommandHandler("exportkeys", exportkeys))
dispatcher.add_handler(CommandHandler("setadmin", setadmin))
dispatcher.add_handler(CommandHandler("purgeexpired", purgeexpired))
dispatcher.add_handler(CommandHandler("renewall", renewall))
dispatcher.add_handler(CommandHandler("addkey", addkey))
dispatcher.add_handler(CommandHandler("resetbot", resetbot))
dispatcher.add_handler(CommandHandler("confirmreset", confirmreset))
dispatcher.add_handler(CommandHandler("lockbot", lockbot))
dispatcher.add_handler(CommandHandler("unlockbot", unlockbot))
dispatcher.add_handler(CommandHandler("maintenance", maintenance))
dispatcher.add_handler(CommandHandler("addadmin", addadmin))
dispatcher.add_handler(CommandHandler("rmadmin", rmadmin))
dispatcher.add_handler(CommandHandler("admins", admins))




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
