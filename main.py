# main.py — Advanced Telegram Auto Forward Bot
# Python 3.11 | telethon 1.36.0 | python-telegram-bot 21.6
# Features: multi-source/target, delay, text filter, blacklist,
#           whitelist, begin/end text, user filter, transform toggles

import asyncio
import logging
import re
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters as tgf,
)
from telethon import TelegramClient, events
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from config import ADMIN_USER_ID, BOT_TOKEN
from database import (
    add_destination,
    add_source,
    delete_session,
    get_all_destinations,
    get_all_sources,
    get_api_creds,
    get_session,
    get_settings,
    get_stats,
    increment_stat,
    init_db,
    remove_destination,
    remove_source,
    save_api_creds,
    save_session,
    save_settings,
)
from filters import apply_placeholders, apply_text_transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ForwardBot")

active_client = None
monitor_running = False
DIV = "━━━━━━━━━━━━━━━━━━━━━━━━"

(
    S_API_ID, S_API_HASH, S_PHONE, S_OTP, S_2FA,
    S_INCOMING, S_OUTGOING,
    S_DELAY, S_FILTER,
    S_BLACKLIST, S_WHITELIST,
    S_BEGIN, S_END, S_FUSERS,
) = range(14)


def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id != ADMIN_USER_ID:
            if update.message:
                await update.message.reply_text("🚫 Access Denied.")
            return ConversationHandler.END
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


def md(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", str(text))


async def _send_main_menu(message):
    s     = get_settings()
    creds = get_api_creds()
    stats = get_stats()
    src   = get_all_sources()
    dst   = get_all_destinations()
    phone = md(creds["phone"]) if creds else "_Not connected_"
    text = (
        f"╔══════════════════════════╗\n"
        f"   🤖 *AUTO FORWARD BOT*\n"
        f"╚══════════════════════════╝\n\n"
        f"⚡ Status: 🟢 *Running* \\| 📱 {phone}\n"
        f"{DIV}\n"
        f"📥 Sources: *{len(src)}* \\| 📤 Targets: *{len(dst)}*\n"
        f"✅ Forwarded: *{stats.get('posts_forwarded',0)}* \\| ❌ Ignored: *{stats.get('posts_ignored',0)}*\n"
        f"⏱ Delay: *{s.get('delay',0)}s* \\| 🔗 URL Preview: *{'On' if s.get('url_preview',True) else 'Off'}*\n"
        f"{DIV}\n\n🎛️ *Choose an option:*"
    )
    kb = [
        [InlineKeyboardButton("📥 /incoming",    callback_data="go:incoming"),  InlineKeyboardButton("📤 /outgoing",     callback_data="go:outgoing")],
        [InlineKeyboardButton("⏱ /delay",         callback_data="go:delay"),    InlineKeyboardButton("🔁 /filter",       callback_data="go:filter")],
        [InlineKeyboardButton("🚫 /blacklist",    callback_data="go:blacklist"), InlineKeyboardButton("✅ /whitelist",    callback_data="go:whitelist")],
        [InlineKeyboardButton("📝 /begin_text",   callback_data="go:begin"),     InlineKeyboardButton("📝 /end_text",     callback_data="go:end")],
        [InlineKeyboardButton("⚙️ /transform",    callback_data="go:transform"), InlineKeyboardButton("👥 /filter_users", callback_data="go:fusers")],
        [InlineKeyboardButton("📊 /status",       callback_data="go:status"),    InlineKeyboardButton("🔓 Logout",        callback_data="go:logout")],
    ]
    await message.reply_text(text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))


@admin_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if get_session() and get_api_creds():
        await _send_main_menu(update.message)
        return ConversationHandler.END
    await update.message.reply_text(
        "╔══════════════════════════╗\n"
        "   🤖 *AUTO FORWARD BOT*\n"
        "╚══════════════════════════╝\n\n"
        "👋 *Welcome\\!* Connect your Telegram account\\.\n\n"
        f"{DIV}\n\n"
        "📌 *Get API credentials from:*\n"
        "👉 https://my\\.telegram\\.org/apps\n\n"
        "🔢 *STEP 1 — Send your API ID:*\n"
        "_\\(numbers only, e\\.g: 12345678\\)_\n\n"
        "❌ /cancel to abort",
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )
    return S_API_ID


async def step_api_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("❌ API ID must be *numbers only*\\. Send again:", parse_mode="MarkdownV2")
        return S_API_ID
    ctx.user_data["api_id"] = int(txt)
    await update.message.reply_text(
        "✅ *API ID saved\\!*\n\n🔑 *STEP 2 — Send your API Hash:*\n_\\(32 character string\\)_\n\n❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_API_HASH


async def step_api_hash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if len(txt) < 10:
        await update.message.reply_text("❌ Invalid API Hash\\. Send again:", parse_mode="MarkdownV2")
        return S_API_HASH
    ctx.user_data["api_hash"] = txt
    await update.message.reply_text(
        "✅ *API Hash saved\\!*\n\n📱 *STEP 3 — Send your Phone Number:*\n_\\(with country code, e\\.g: \\+919876543210\\)_\n\n❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_PHONE


async def step_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    ctx.user_data["phone"] = phone
    await update.message.reply_text(f"⏳ Sending OTP to `{md(phone)}`\\.\\.\\.", parse_mode="MarkdownV2")
    try:
        client = TelegramClient(StringSession(), ctx.user_data["api_id"], ctx.user_data["api_hash"])
        await client.connect()
        result = await client.send_code_request(phone)
        ctx.user_data["client"]     = client
        ctx.user_data["phone_hash"] = result.phone_code_hash
        await update.message.reply_text(
            "📲 *OTP Sent\\!*\n\n🔢 *STEP 4 — Send the OTP:*\n_\\(check your Telegram app\\)_\n\n❌ /cancel",
            parse_mode="MarkdownV2",
        )
        return S_OTP
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Failed to send OTP\\!*\n`{md(str(e))}`\n\nCheck your API ID / Hash and try /start again\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END


async def step_otp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip().replace(" ", "")
    client = ctx.user_data["client"]
    phone  = ctx.user_data["phone"]
    try:
        await client.sign_in(phone=phone, code=otp, phone_code_hash=ctx.user_data["phone_hash"])
        await _finish_login(update, ctx, client)
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔒 *2FA Password Required\\!*\n\n🔑 *STEP 5 — Send your 2FA Password:*\n\n❌ /cancel",
            parse_mode="MarkdownV2",
        )
        return S_2FA
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await update.message.reply_text("❌ *Wrong or Expired OTP\\!* Send again:\n\n❌ /cancel", parse_mode="MarkdownV2")
        return S_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Login error: `{md(str(e))}`\n\nTry /start again\\.", parse_mode="MarkdownV2")
        return ConversationHandler.END


async def step_2fa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    client = ctx.user_data["client"]
    try:
        await client.sign_in(password=update.message.text.strip())
        await _finish_login(update, ctx, client)
        return ConversationHandler.END
    except Exception:
        await update.message.reply_text("❌ *Wrong 2FA password\\!* Try again:\n\n❌ /cancel", parse_mode="MarkdownV2")
        return S_2FA


async def _finish_login(update: Update, ctx, client: TelegramClient):
    session_str = client.session.save()
    save_session(session_str)
    save_api_creds(ctx.user_data["api_id"], ctx.user_data["api_hash"], ctx.user_data["phone"])
    me    = await client.get_me()
    phone = ctx.user_data["phone"]
    await update.message.reply_text(
        f"🎉 *Login Successful\\!*\n\n"
        f"👤 Name: {md(me.first_name or '')}\n"
        f"📱 Phone: `{md(phone)}`\n"
        f"🆔 User ID: `{me.id}`\n\n"
        f"✅ Account connected\\!\n⏳ Starting monitor\\.\\.\\.",
        parse_mode="MarkdownV2",
    )
    await _launch_userbot(client)
    await _send_main_menu(update.message)


@admin_only
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send_main_menu(update.message)


@admin_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _reply_status(update.message)


async def _reply_status(msg):
    global monitor_running
    s         = get_settings()
    stats     = get_stats()
    src       = get_all_sources()
    dst       = get_all_destinations()
    creds     = get_api_creds()
    checked   = stats.get("posts_checked", 0)
    forwarded = stats.get("posts_forwarded", 0)
    ignored   = stats.get("posts_ignored", 0)
    rate      = f"{forwarded/checked*100:.1f}%" if checked else "N/A"
    src_list  = "\n".join(f"  🟢 `{md(r['identifier'])}`" for r in src) or "  _None_"
    dst_list  = "\n".join(f"  🔵 `{md(r['identifier'])}`" for r in dst) or "  _None_"
    phone     = md(creds["phone"]) if creds else "N/A"
    def b(k, d=False): return "✅" if s.get(k, d) else "❌"
    await msg.reply_text(
        f"╔══════════════════════════╗\n          📊 *BOT STATUS*\n╚══════════════════════════╝\n\n"
        f"⚡ System: 🟢 Running\n🔄 Monitor: {'🟢 Active' if monitor_running else '🔴 Inactive'}\n📱 Account: `{phone}`\n"
        f"{DIV}\n\n📥 *Sources \\({len(src)}\\):*\n{src_list}\n\n📤 *Targets \\({len(dst)}\\):*\n{dst_list}\n\n"
        f"{DIV}\n\n"
        f"⏱ Delay: `{s.get('delay',0)}s` \\| 🔗 URL Preview: {b('url_preview',True)}\n"
        f"↩️ Fwd Header: {b('should_forward')} \\| ✏️ Sync Edits: {b('should_edit')}\n"
        f"🗑️ Sync Del: {b('should_delete')} \\| 📝 Monospace: {b('monospace')}\n"
        f"🖼️ Media: {b('send_media',True)} \\| 💬 Text: {b('send_text',True)}\n"
        f"🚫 Blacklist: `{len(s.get('blacklist',[]))} words` \\| ✅ Whitelist: `{len(s.get('whitelist',[]))} words`\n"
        f"🔁 Replacements: `{len(s.get('replacements',[]))}` \\| 👥 User filter: `{len(s.get('filter_users',[]))}`\n"
        f"📝 Begin: `{'Set' if s.get('begin_text') else 'None'}` \\| End: `{'Set' if s.get('end_text') else 'None'}`\n\n"
        f"{DIV}\n\n📝 Checked: `{checked}` \\| ✅ Forwarded: `{forwarded}` \\| ❌ Ignored: `{ignored}` \\| 📈 Rate: `{rate}`",
        parse_mode="MarkdownV2",
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ *Cancelled\\.* Use /menu to open main menu\\.", parse_mode="MarkdownV2")
    return ConversationHandler.END


@admin_only
async def cmd_incoming(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_all_sources()
    lst  = "\n".join(f"  🟢 `{md(r['identifier'])}`" for r in rows) or "  _None_"
    await update.message.reply_text(
        f"📥 *INCOMING \\(SOURCE CHATS\\)*\n{DIV}\n\n📋 *Current sources \\({len(rows)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"📌 *How to use:*\n• `\\+@channel` — add source\n• `\\-@channel` — remove source\n• Private chat: `\\-1001234567890`\n\n"
        f"✅ Send /done when finished \\| ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_INCOMING


async def handle_incoming(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        rows = get_all_sources()
        lst  = "\n".join(f"  🟢 `{md(r['identifier'])}`" for r in rows) or "  _None_"
        await update.message.reply_text(f"✅ *Done\\!*\n\n📥 *Sources \\({len(rows)}\\):*\n{lst}", parse_mode="MarkdownV2")
        return ConversationHandler.END
    if txt.startswith("+"):
        ch = txt[1:].strip()
        if add_source(ch):
            await update.message.reply_text(f"✅ *Added:* `{md(ch)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"⚠️ `{md(ch)}` already exists\\.", parse_mode="MarkdownV2")
    elif txt.startswith("-"):
        ch = txt[1:].strip()
        if remove_source(ch):
            await update.message.reply_text(f"🗑️ *Removed:* `{md(ch)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"❌ `{md(ch)}` not found\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("📌 Use `\\+@channel` to add or `\\-@channel` to remove\\.", parse_mode="MarkdownV2")
    return S_INCOMING


@admin_only
async def cmd_outgoing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_all_destinations()
    lst  = "\n".join(f"  🔵 `{md(r['identifier'])}`" for r in rows) or "  _None_"
    await update.message.reply_text(
        f"📤 *OUTGOING \\(TARGET CHATS\\)*\n{DIV}\n\n📋 *Current targets \\({len(rows)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"📌 *How to use:*\n• `\\+@channel` — add target\n• `\\-@channel` — remove target\n• Bot must be *admin* in target channels\\!\n\n"
        f"✅ Send /done when finished \\| ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_OUTGOING


async def handle_outgoing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        rows = get_all_destinations()
        lst  = "\n".join(f"  🔵 `{md(r['identifier'])}`" for r in rows) or "  _None_"
        await update.message.reply_text(f"✅ *Done\\!*\n\n📤 *Targets \\({len(rows)}\\):*\n{lst}", parse_mode="MarkdownV2")
        return ConversationHandler.END
    if txt.startswith("+"):
        ch = txt[1:].strip()
        if add_destination(ch):
            await update.message.reply_text(f"✅ *Added:* `{md(ch)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"⚠️ `{md(ch)}` already exists\\.", parse_mode="MarkdownV2")
    elif txt.startswith("-"):
        ch = txt[1:].strip()
        if remove_destination(ch):
            await update.message.reply_text(f"🗑️ *Removed:* `{md(ch)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"❌ `{md(ch)}` not found\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("📌 Use `\\+@channel` to add or `\\-@channel` to remove\\.", parse_mode="MarkdownV2")
    return S_OUTGOING


@admin_only
async def cmd_delay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur = get_settings().get("delay", 0)
    await update.message.reply_text(
        f"⏱ *DELAY SETTINGS*\n{DIV}\n\n⏳ Current: *{cur} seconds*\n\n"
        f"📝 Send delay in seconds:\n• `0` \\= no delay\n• `30` \\= 30 seconds\n• `60` \\= 1 minute\n\n❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_DELAY


async def handle_delay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("❌ Send a number \\(seconds\\), e\\.g: `30`", parse_mode="MarkdownV2")
        return S_DELAY
    s = get_settings()
    s["delay"] = int(txt)
    save_settings(s)
    note = "⚡ Instant forwarding\\." if int(txt) == 0 else f"⏱ {txt}s delay before forwarding\\."
    await update.message.reply_text(f"✅ *Delay set to {txt}s\\!*\n\n{note}", parse_mode="MarkdownV2")
    return ConversationHandler.END


@admin_only
async def cmd_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reps = get_settings().get("replacements", [])
    lst  = "\n".join(f"  • `{md(r['find'])}` → `{md(r['replace']) or '(remove)'}`" for r in reps) or "  _None_"
    await update.message.reply_text(
        f"🔁 *TEXT FILTER / REPLACE*\n{DIV}\n\n📋 *Current rules \\({len(reps)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"📌 *Format:* `find::replace`\n\n*Examples:*\n"
        f"• `oldword::newword` — replace\n• `badword::` — remove\n• `url::` — remove all URLs\n• `username::` — remove all @mentions\n\n"
        f"*Placeholders in replace field:*\n`[user.username]` `[user.id]` `[user.first_name]` `[user.last_name]`\n\n"
        f"One rule per message\\. /done when finished\\. ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    ctx.user_data["reps"] = list(reps)
    return S_FILTER


async def handle_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        s = get_settings()
        s["replacements"] = ctx.user_data.get("reps", [])
        save_settings(s)
        await update.message.reply_text(f"✅ *Filter saved\\!* `{len(s['replacements'])}` rule\\(s\\) active\\.", parse_mode="MarkdownV2")
        return ConversationHandler.END
    if "::" not in txt:
        await update.message.reply_text("📌 Format: `find::replace` or `removeword::`\n\nSend again or /done", parse_mode="MarkdownV2")
        return S_FILTER
    parts   = txt.split("::", 1)
    find    = parts[0].strip()
    replace = parts[1].strip()
    if not find:
        await update.message.reply_text("❌ Find field cannot be empty\\.", parse_mode="MarkdownV2")
        return S_FILTER
    reps = ctx.user_data.setdefault("reps", [])
    reps[:] = [r for r in reps if r["find"] != find]
    reps.append({"find": find, "replace": replace})
    action = f"`{md(find)}` → `{md(replace)}`" if replace else f"Remove `{md(find)}`"
    await update.message.reply_text(f"✅ *Rule added:* {action}\n\nSend more or /done", parse_mode="MarkdownV2")
    return S_FILTER


@admin_only
async def cmd_blacklist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bl  = get_settings().get("blacklist", [])
    lst = "\n".join(f"  🚫 `{md(k)}`" for k in bl) or "  _None_"
    await update.message.reply_text(
        f"🚫 *BLACKLIST KEYWORDS*\n{DIV}\n\n📋 *Current \\({len(bl)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"• `\\+keyword` — add\n• `\\-keyword` — remove\n\n⛔ Posts with blacklisted words will be *ignored*\\.\n\n/done when finished \\| ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_BLACKLIST


async def handle_blacklist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        return ConversationHandler.END
    s  = get_settings()
    bl = s.get("blacklist", [])
    if txt.startswith("+"):
        kw = txt[1:].strip().lower()
        if kw and kw not in bl:
            bl.append(kw); s["blacklist"] = bl; save_settings(s)
            await update.message.reply_text(f"✅ *Blacklisted:* `{md(kw)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text("⚠️ Already exists or empty\\.", parse_mode="MarkdownV2")
    elif txt.startswith("-"):
        kw = txt[1:].strip().lower()
        if kw in bl:
            bl.remove(kw); s["blacklist"] = bl; save_settings(s)
            await update.message.reply_text(f"🗑️ *Removed:* `{md(kw)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"❌ `{md(kw)}` not found\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("📌 Use `\\+keyword` to add or `\\-keyword` to remove\\.", parse_mode="MarkdownV2")
    return S_BLACKLIST


@admin_only
async def cmd_whitelist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wl  = get_settings().get("whitelist", [])
    lst = "\n".join(f"  ✅ `{md(k)}`" for k in wl) or "  _None \\(all posts forwarded\\)_"
    await update.message.reply_text(
        f"✅ *WHITELIST KEYWORDS*\n{DIV}\n\n📋 *Current \\({len(wl)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"• `\\+keyword` — add\n• `\\-keyword` — remove\n\n✅ Only posts *containing* whitelisted words will be forwarded\\.\n"
        f"💡 Empty \\= forward all valid posts\\.\n\n/done when finished \\| ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_WHITELIST


async def handle_whitelist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        return ConversationHandler.END
    s  = get_settings()
    wl = s.get("whitelist", [])
    if txt.startswith("+"):
        kw = txt[1:].strip().lower()
        if kw and kw not in wl:
            wl.append(kw); s["whitelist"] = wl; save_settings(s)
            await update.message.reply_text(f"✅ *Whitelisted:* `{md(kw)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text("⚠️ Already exists or empty\\.", parse_mode="MarkdownV2")
    elif txt.startswith("-"):
        kw = txt[1:].strip().lower()
        if kw in wl:
            wl.remove(kw); s["whitelist"] = wl; save_settings(s)
            await update.message.reply_text(f"🗑️ *Removed:* `{md(kw)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"❌ `{md(kw)}` not found\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("📌 Use `\\+keyword` to add or `\\-keyword` to remove\\.", parse_mode="MarkdownV2")
    return S_WHITELIST


@admin_only
async def cmd_begin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur = get_settings().get("begin_text", "")
    await update.message.reply_text(
        f"📝 *BEGIN TEXT*\n{DIV}\n\nCurrent: `{md(cur) if cur else 'None'}`\n\n"
        f"Added *before* every forwarded message\\.\n\n"
        f"*Placeholders:* `[user.username]` `[user.id]` `[user.first_name]` `[user.last_name]`\n\n"
        f"Send new text or `clear` to remove\\. ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_BEGIN


@admin_only
async def cmd_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur = get_settings().get("end_text", "")
    await update.message.reply_text(
        f"📝 *END TEXT*\n{DIV}\n\nCurrent: `{md(cur) if cur else 'None'}`\n\n"
        f"Added *after* every forwarded message\\.\n\n"
        f"*Placeholders:* `[user.username]` `[user.id]` `[user.first_name]` `[user.last_name]`\n\n"
        f"Send new text or `clear` to remove\\. ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_END


async def handle_begin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = get_settings()
    if update.message.text.strip().lower() == "clear":
        s["begin_text"] = ""
    else:
        s["begin_text"] = update.message.text.strip()
    save_settings(s)
    await update.message.reply_text("✅ *Begin text saved\\!*" if s["begin_text"] else "🗑️ *Begin text cleared\\!*", parse_mode="MarkdownV2")
    return ConversationHandler.END


async def handle_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = get_settings()
    if update.message.text.strip().lower() == "clear":
        s["end_text"] = ""
    else:
        s["end_text"] = update.message.text.strip()
    save_settings(s)
    await update.message.reply_text("✅ *End text saved\\!*" if s["end_text"] else "🗑️ *End text cleared\\!*", parse_mode="MarkdownV2")
    return ConversationHandler.END


@admin_only
async def cmd_fusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fu  = get_settings().get("filter_users", [])
    lst = "\n".join(f"  👤 `{md(u)}`" for u in fu) or "  _None \\(all users allowed\\)_"
    await update.message.reply_text(
        f"👥 *FILTER USERS*\n{DIV}\n\n📋 *Whitelisted \\({len(fu)}\\):*\n{lst}\n\n{DIV}\n\n"
        f"Forward only messages from these users \\(in groups\\)\\.\nEmpty \\= allow all users\\.\n\n"
        f"• `\\+@username` or `\\+userid` — add\n• `\\-@username` or `\\-userid` — remove\n\n"
        f"/done when finished \\| ❌ /cancel",
        parse_mode="MarkdownV2",
    )
    return S_FUSERS


async def handle_fusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "/done":
        return ConversationHandler.END
    s  = get_settings()
    fu = s.get("filter_users", [])
    if txt.startswith("+"):
        u = txt[1:].strip()
        if u and u not in fu:
            fu.append(u); s["filter_users"] = fu; save_settings(s)
            await update.message.reply_text(f"✅ *Added:* `{md(u)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text("⚠️ Already exists or empty\\.", parse_mode="MarkdownV2")
    elif txt.startswith("-"):
        u = txt[1:].strip()
        if u in fu:
            fu.remove(u); s["filter_users"] = fu; save_settings(s)
            await update.message.reply_text(f"🗑️ *Removed:* `{md(u)}`\n\nSend more or /done", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"❌ `{md(u)}` not found\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("📌 Use `\\+@username` to add or `\\-@username` to remove\\.", parse_mode="MarkdownV2")
    return S_FUSERS


@admin_only
async def cmd_transform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _render_transform(update.message, edit=False)


async def _render_transform(target, edit=False):
    s = get_settings()
    def tog(k, d=False): return "✅ ON" if s.get(k, d) else "❌ OFF"
    kb = [
        [InlineKeyboardButton(f"🔗 URL Preview: {tog('url_preview',True)}",       callback_data="toggle:url_preview:True")],
        [InlineKeyboardButton(f"↩️ Forward Header: {tog('should_forward')}",      callback_data="toggle:should_forward:False")],
        [InlineKeyboardButton(f"✏️ Sync Edits: {tog('should_edit')}",             callback_data="toggle:should_edit:False")],
        [InlineKeyboardButton(f"🗑️ Sync Deletes: {tog('should_delete')}",        callback_data="toggle:should_delete:False")],
        [InlineKeyboardButton(f"🖼️ Send Media: {tog('send_media',True)}",         callback_data="toggle:send_media:True")],
        [InlineKeyboardButton(f"💬 Send Text: {tog('send_text',True)}",           callback_data="toggle:send_text:True")],
        [InlineKeyboardButton(f"📝 Monospace: {tog('monospace')}",                callback_data="toggle:monospace:False")],
        [InlineKeyboardButton("🏠 Main Menu",                                      callback_data="go:back")],
    ]
    text = f"⚙️ *TRANSFORM SETTINGS*\n{DIV}\n\nTap any button to toggle:"
    if edit:
        await target.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await target.reply_text(text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))


async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global active_client, monitor_running
    query = update.callback_query
    await query.answer()
    data  = query.data
    if data.startswith("toggle:"):
        _, key, default_str = data.split(":", 2)
        s       = get_settings()
        s[key]  = not s.get(key, default_str == "True")
        save_settings(s)
        await _render_transform(query, edit=True)
        return
    if data == "go:transform":
        await _render_transform(query, edit=True)
        return
    if data == "go:back":
        s = get_settings(); creds = get_api_creds(); stats = get_stats()
        src = get_all_sources(); dst = get_all_destinations()
        phone = md(creds["phone"]) if creds else "_Not connected_"
        text = (
            f"╔══════════════════════════╗\n   🤖 *AUTO FORWARD BOT*\n╚══════════════════════════╝\n\n"
            f"⚡ 🟢 Running \\| 📱 {phone}\n{DIV}\n"
            f"📥 Sources: *{len(src)}* \\| 📤 Targets: *{len(dst)}*\n"
            f"✅ Forwarded: *{stats.get('posts_forwarded',0)}* \\| ⏱ Delay: *{s.get('delay',0)}s*\n{DIV}"
        )
        kb = [
            [InlineKeyboardButton("📥 /incoming", callback_data="go:incoming"), InlineKeyboardButton("📤 /outgoing", callback_data="go:outgoing")],
            [InlineKeyboardButton("⏱ /delay", callback_data="go:delay"), InlineKeyboardButton("🔁 /filter", callback_data="go:filter")],
            [InlineKeyboardButton("🚫 /blacklist", callback_data="go:blacklist"), InlineKeyboardButton("✅ /whitelist", callback_data="go:whitelist")],
            [InlineKeyboardButton("📝 /begin_text", callback_data="go:begin"), InlineKeyboardButton("📝 /end_text", callback_data="go:end")],
            [InlineKeyboardButton("⚙️ /transform", callback_data="go:transform"), InlineKeyboardButton("👥 /filter_users", callback_data="go:fusers")],
            [InlineKeyboardButton("📊 /status", callback_data="go:status"), InlineKeyboardButton("🔓 Logout", callback_data="go:logout")],
        ]
        await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "go:status":
        s = get_settings(); stats = get_stats(); src = get_all_sources(); dst = get_all_destinations(); creds = get_api_creds()
        checked = stats.get("posts_checked", 0); forwarded = stats.get("posts_forwarded", 0); ignored = stats.get("posts_ignored", 0)
        rate = f"{forwarded/checked*100:.1f}%" if checked else "N/A"
        src_list = "\n".join(f"  🟢 `{md(r['identifier'])}`" for r in src) or "  _None_"
        dst_list = "\n".join(f"  🔵 `{md(r['identifier'])}`" for r in dst) or "  _None_"
        phone = md(creds["phone"]) if creds else "N/A"
        text = (
            f"📊 *BOT STATUS*\n{DIV}\n\n⚡ 🟢 Running \\| 📱 `{phone}`\n"
            f"🔄 Monitor: {'🟢 Active' if monitor_running else '🔴 Inactive'}\n\n"
            f"📥 *Sources \\({len(src)}\\):*\n{src_list}\n\n📤 *Targets \\({len(dst)}\\):*\n{dst_list}\n\n"
            f"{DIV}\n\n📝 `{checked}` \\| ✅ `{forwarded}` \\| ❌ `{ignored}` \\| 📈 `{rate}`"
        )
        kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="go:status"), InlineKeyboardButton("🏠 Back", callback_data="go:back")]]
        await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "go:logout":
        kb = [[InlineKeyboardButton("✅ Yes, Logout", callback_data="do:logout")], [InlineKeyboardButton("❌ Cancel", callback_data="go:back")]]
        await query.edit_message_text("🔓 *Logout?*\n\nThis will disconnect your account and stop monitoring\\.", parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "do:logout":
        delete_session()
        if active_client:
            try:
                await active_client.disconnect()
            except:
                pass
        active_client = None
        monitor_running = False
        await query.edit_message_text("🔓 *Logged out\\!*\n\nUse /start to login again\\.", parse_mode="MarkdownV2")
        return
    hints = {"go:incoming": "/incoming", "go:outgoing": "/outgoing", "go:delay": "/delay",
             "go:filter": "/filter", "go:blacklist": "/blacklist", "go:whitelist": "/whitelist",
             "go:begin": "/begin_text", "go:end": "/end_text", "go:fusers": "/filter_users"}
    if data in hints:
        await query.answer(f"Send {hints[data]} command", show_alert=True)


async def _launch_userbot(client: TelegramClient = None):
    global active_client, monitor_running
    if monitor_running:
        return
    if client is None:
        creds = get_api_creds(); session_str = get_session()
        if not creds or not session_str:
            return
        client = TelegramClient(StringSession(session_str), creds["api_id"], creds["api_hash"])
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Session not authorized — re-login required.")
            return
    active_client = client
    monitor_running = True

    @active_client.on(events.NewMessage())
    async def on_new(event):
        await _process(event)

    @active_client.on(events.MessageEdited())
    async def on_edit(event):
        if get_settings().get("should_edit", False):
            await _process(event)

    asyncio.ensure_future(active_client.run_until_disconnected())
    logger.info("✅ Userbot monitor started")


async def _get_sender_info(event) -> dict:
    info = {"username": "", "id": "", "first_name": "", "last_name": ""}
    try:
        sender = await event.get_sender()
        if sender:
            info["username"]   = f"@{sender.username}" if getattr(sender, "username", None) else ""
            info["id"]         = str(sender.id)
            info["first_name"] = getattr(sender, "first_name", "") or ""
            info["last_name"]  = getattr(sender, "last_name",  "") or ""
    except Exception:
        pass
    return info


async def _process(event):
    global active_client
    sources = [r["identifier"] for r in get_all_sources()]
    if not sources:
        return
    try:
        chat          = await event.get_chat()
        chat_username = getattr(chat, "username", None)
        chat_id_str   = str(event.chat_id)

        matched = False
        for src in sources:
            clean = src.lstrip("@").lower()
            if chat_username and chat_username.lower() == clean:
                matched = True; break
            if clean == chat_id_str or clean == chat_id_str.lstrip("-"):
                matched = True; break
        if not matched:
            return

        msg = event.message; s = get_settings()
        raw_text = msg.text or msg.caption or ""
        has_photo = msg.photo is not None
        increment_stat("posts_checked")

        fu = s.get("filter_users", [])
        if fu:
            si = await _get_sender_info(event)
            uid = si["id"]; uname = si["username"].lstrip("@").lower()
            if not any(u.lstrip("+@").lower() == uname or u.lstrip("+") == uid for u in fu):
                increment_stat("posts_ignored"); return

        bl = s.get("blacklist", [])
        if bl and any(kw in raw_text.lower() for kw in bl):
            increment_stat("posts_ignored"); return

        wl = s.get("whitelist", [])
        if wl and not any(kw in raw_text.lower() for kw in wl):
            increment_stat("posts_ignored"); return

        send_media = s.get("send_media", True)
        send_text  = s.get("send_text",  True)
        if not send_media and has_photo:
            increment_stat("posts_ignored"); return

        text = raw_text if send_text else ""

        reps = s.get("replacements", [])
        if reps and text:
            text = apply_text_transform(text, reps)

        if s.get("monospace", False) and text:
            text = f"`{text}`"

        si    = await _get_sender_info(event)
        text  = apply_placeholders(text, si)
        begin = apply_placeholders(s.get("begin_text", ""), si)
        end   = apply_placeholders(s.get("end_text",   ""), si)
        if begin: text = begin + "\n" + text
        if end:   text = text + "\n" + end
        text = text.strip()

        delay = s.get("delay", 0)
        if delay > 0:
            await asyncio.sleep(delay)

        destinations = get_all_destinations()
        if not destinations:
            increment_stat("posts_ignored"); return

        forwarded_any = False
        for dest in destinations:
            dest_id = dest["identifier"]
            try:
                if s.get("should_forward", False):
                    await active_client.forward_messages(dest_id, msg)
                elif has_photo and send_media:
                    photo_bytes = await active_client.download_media(msg.photo, bytes)
                    await active_client.send_file(dest_id, file=photo_bytes, caption=text or None, link_preview=s.get("url_preview", True))
                elif text:
                    await active_client.send_message(dest_id, text, link_preview=s.get("url_preview", True))
                else:
                    continue
                forwarded_any = True
                logger.info("✅ Forwarded to %s", dest_id)
            except Exception as e:
                logger.error("❌ Forward to %s failed: %s", dest_id, e)

        if forwarded_any:
            increment_stat("posts_forwarded")
        else:
            increment_stat("posts_ignored")

    except Exception as e:
        logger.error("_process error: %s", e)


async def main():
    init_db()
    logger.info("🚀 Starting Advanced Forwarder Bot …")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            S_API_ID:   [MessageHandler(tgf.TEXT & ~tgf.COMMAND, step_api_id)],
            S_API_HASH: [MessageHandler(tgf.TEXT & ~tgf.COMMAND, step_api_hash)],
            S_PHONE:    [MessageHandler(tgf.TEXT & ~tgf.COMMAND, step_phone)],
            S_OTP:      [MessageHandler(tgf.TEXT & ~tgf.COMMAND, step_otp)],
            S_2FA:      [MessageHandler(tgf.TEXT & ~tgf.COMMAND, step_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_message=False,
    )

    def _conv(cmd, entry_fn, state_id, handler_fn):
        return ConversationHandler(
            entry_points=[CommandHandler(cmd, entry_fn)],
            states={state_id: [
                MessageHandler(tgf.TEXT & ~tgf.COMMAND, handler_fn),
                CommandHandler("done", handler_fn),
            ]},
            fallbacks=[CommandHandler("cancel", cmd_cancel)],
            per_message=False,
        )

    for conv in [
        login_conv,
        _conv("incoming",     cmd_incoming, S_INCOMING, handle_incoming),
        _conv("outgoing",     cmd_outgoing, S_OUTGOING, handle_outgoing),
        _conv("delay",        cmd_delay,    S_DELAY,    handle_delay),
        _conv("blacklist",    cmd_blacklist,S_BLACKLIST,handle_blacklist),
        _conv("whitelist",    cmd_whitelist,S_WHITELIST,handle_whitelist),
        _conv("begin_text",   cmd_begin,    S_BEGIN,    handle_begin),
        _conv("end_text",     cmd_end,      S_END,      handle_end),
        _conv("filter_users", cmd_fusers,   S_FUSERS,   handle_fusers),
        ConversationHandler(
            entry_points=[CommandHandler("filter", cmd_filter)],
            states={S_FILTER: [MessageHandler(tgf.TEXT & ~tgf.COMMAND, handle_filter), CommandHandler("done", handle_filter)]},
            fallbacks=[CommandHandler("cancel", cmd_cancel)],
            per_message=False,
        ),
    ]:
        app.add_handler(conv)

    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(CommandHandler("menu",      cmd_menu))
    app.add_handler(CommandHandler("transform", cmd_transform))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))

    # Restore session on startup
    session_str = get_session()
    creds = get_api_creds()
    if session_str and creds:
        try:
            client = TelegramClient(StringSession(session_str), creds["api_id"], creds["api_hash"])
            await client.connect()
            if await client.is_user_authorized():
                await _launch_userbot(client)
                logger.info("✅ Session restored — monitor running")
            else:
                logger.warning("⚠️ Session expired — re-login required via bot")
        except Exception as e:
            logger.error("Session restore error: %s", e)

    logger.info("🤖 Bot online — send /start in Telegram")

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()  # run forever
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
