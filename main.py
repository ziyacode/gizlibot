from datetime import datetime, timedelta, timezone
import asyncio
import os
import re
import sys
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, ".vendor")
VENDOR_TELEGRAM_INIT = os.path.join(VENDOR_DIR, "telegram", "__init__.py")
if os.path.isfile(VENDOR_TELEGRAM_INIT) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)


def load_env_file(path: str):
    if not os.path.isfile(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue

            os.environ[key] = value.strip().strip('"').strip("'")


load_env_file(os.path.join(BASE_DIR, ".env"))

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

import os

SECRETS = {}
USER_NAMES_BY_ID = {}
USER_NAMES_BY_USERNAME = {}
PENDING_REPLY_SECRETS = {}
BOT_USERNAME = None

DURATION_RE = re.compile(r"^(\d+)([sdhm])$", re.IGNORECASE)
USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,64}")
USER_ID_RE = re.compile(r"\d{8,12}")
PUBLIC_READER_LIMIT_RE = re.compile(r"\d{1,2}")
BAKU_TZ = timezone(timedelta(hours=4), "Asia/Baku")
BAKU_TIME_LABEL = "Bakı vaxtı"
REPLY_SECRET_NO_REPLY_TEXT = "Kiminsə mesajına reply edib belə yaz: /gizli və gözlə"
REPLY_SECRET_EXTRA_TEXT_ERROR = (
    "Qrupda reply edərək, yalnız /gizli yazmalısan, "
    "gizli mesajı isə botun şəxsisinə yazacaqsan."
)

BOT_SHORT_DESCRIPTION = "Qruplarda @username və Telegram ID ilə gizli mesaj göndər."

BOT_DESCRIPTION = (
    "Qruplarda gizli mesaj göndər: @username və ya 8-12 rəqəmli Telegram ID ilə tək və çoxlu alıcı seç. "
    "Bot qrupda olanda reply etdiyin şəxsi avtomatik alıcı kimi tanıya bilir. "
    "Mesaj qrupda məzmun kimi görünmür, alıcı popup ilə bir dəfə açır. "
    "Nümunə: @ZiyaGizliBot 7823137189 salam"
)

START_TEXT = (
    "Salam. Mən qrup içində inline işləyən gizli mesaj botuyam.\n\n"
    "Nə edə bilirəm:\n"
    "• @username və Telegram ID ilə tək nəfərə gizli mesaj göndərirəm\n"
    "• Bir neçə nəfərə eyni gizli mesaj göndərirəm\n"
    "• Bot qrupda olanda reply ilə alıcını avtomatik tanıyıram\n"
    "• Mesaja vaxt limiti qoya bilirəm\n"
    "• Kimin nə vaxt oxuduğunu qeyd edirəm\n"
    "• Bütün hədəflər oxuyandan sonra düyməni bağlayıram\n\n"
    "ID ilə nümunə:\n"
    "@ZiyaGizliBot 7823137189 salam necesen\n\n"
    "Çoxlu ID ilə nümunə:\n"
    "@ZiyaGizliBot 7823137189 1234567890 9876543210 salam dostlar\n\n"
    "Reply ilə nümunə:\n"
    "Kiminsə mesajına reply edib qrupda /gizli yaz, gizli mətni botun şəxsi mesajında göndər.\n\n"
    "İstifadə qaydalarını görmək üçün /help yaz."
)

HELP_TEXT = (
    "İstifadə qaydası:\n\n"
    "1. Tək nəfərə username ilə mesaj:\n"
    "@ZiyaGizliBot @istifadeciadi salam dostum\n\n"
    "2. Tək nəfərə Telegram ID ilə mesaj:\n"
    "@ZiyaGizliBot 7823137189 salam necesen\n\n"
    "3. Vaxt limiti ilə:\n"
    "@ZiyaGizliBot 1h @istifadeciadi salam dostum\n"
    "@ZiyaGizliBot 1h 7823137189 salam dostum\n"
    "@ZiyaGizliBot 1d @istifadeciadi salam dostum\n"
    "@ZiyaGizliBot 30s @istifadeciadi salam dostum\n\n"
    "Alıcı yazmadan ilk açanlara mesaj:\n"
    "@ZiyaGizliBot salam dostum\n"
    "@ZiyaGizliBot 3 salam dostlar\n"
    "@ZiyaGizliBot 1h 3 salam dostlar\n\n"
    "Vaxt formatı:\n"
    "• s = saniyə\n"
    "• d = dəqiqə\n"
    "• h = saat\n"
    "• m = dəqiqə üçün əlavə alternativ dəstək\n\n"
    "4. Bir neçə nəfərə eyni mesaj:\n"
    "@ZiyaGizliBot (@tagelemep, @salamureg, @alimamedov) salam dostlar\n\n"
    "5. Bir neçə Telegram ID ilə eyni mesaj:\n"
    "@ZiyaGizliBot 7823137189 1234567890 9876543210 salam dostlar\n\n"
    "6. Username və ID qarışıq yazmaq:\n"
    "@ZiyaGizliBot (@tagelemep, 7823137189, 1234567890) salam dostlar\n\n"
    "7. Bir neçə nəfərə vaxt limiti ilə:\n"
    "@ZiyaGizliBot 1h (@tagelemep, @salamureg, @alimamedov) salam dostlar\n\n"
    "8. Reply ilə avtomatik alıcı seçmək:\n"
    "Qrupda kiminsə mesajına reply edib yalnız bunu yaz:\n"
    "/gizli\n"
    "Sonra gizli mətni botun şəxsi mesajında göndər.\n"
    "Vaxt limiti ilə:\n"
    "/gizli 1h\n\n"
    "Qeyd:\n"
    "• Mesajı yalnız qeyd olunan istifadəçilər aça bilər\n"
    "• Inline rejimdə Telegram reply olunan şəxsi bota göndərmir; reply üçün bot qrupda olmalı və /gizli istifadə olunmalıdır\n"
    "• Reply ilə gizli mesajda mətni qrupda yazma, botun şəxsi mesajında yaz\n"
    "• Reply mesajındakı açıq mətnin silinməsi üçün botun qrupda mesaj silmə icazəsi olmalıdır\n"
    "• Alıcı yazmadan adi mətn göndərsən, mesajı ilk 1 nəfər aça bilər\n"
    "• Mətnin əvvəlində 1-2 rəqəmli say yazsan, mesajı ilk o qədər nəfər aça bilər\n"
    "• ID ilə yazanda alıcı ID-si gizli mesajın üstündə görünür\n"
    "• Alıcı mesajı açanda adı oxunma statistikasında görünür\n"
    "• Vaxt bitəndən sonra mesaj açılmır\n"
    "• Mesaj hər alıcı üçün yalnız bir dəfə açılır\n"
    "• Telegram botları ekran görüntüsünü tam bloklaya bilmir; bot məzmunu qrupda saxlamır və popup kimi göstərir"
)

ABOUT_TEXT = (
    BOT_DESCRIPTION
    + "\n\n"
    "Əsas formatlar:\n"
    "@ZiyaGizliBot @istifadeciadi salam\n"
    "@ZiyaGizliBot 7823137189 salam\n"
    "@ZiyaGizliBot 7823137189 1234567890 9876543210 salam\n"
    "Reply formatı: kiminsə mesajına reply edib qrupda /gizli yaz, gizli mətni private-da göndər"
)


def get_bot_token():
    token = os.getenv("TOKEN") or os.getenv("BOT_TOKEN")
    if token:
        return token

    print(
        "TOKEN tapılmadı. Layihə qovluğunda .env faylı yaradıb içinə belə yaz:\n"
        "TOKEN=BotFather-dan-aldığın-token"
    )
    return None


def ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def now_local() -> datetime:
    return datetime.now(BAKU_TZ)


def format_clock(dt: datetime) -> str:
    return dt.astimezone(BAKU_TZ).strftime("%H:%M:%S")


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def user_display_name(user) -> str:
    username = normalize_username(user.username or "")
    return user.full_name or user.first_name or (f"@{username}" if username else f"ID {user.id}")


def make_sender_info(user):
    if not user:
        return None

    remember_user(user)
    return {
        "user_id": user.id,
        "username": normalize_username(user.username or ""),
        "display_name": user_display_name(user),
    }


def sender_display_name(sender: dict) -> str:
    display_name = sender.get("display_name") or f"ID {sender.get('user_id')}"
    username = sender.get("username")
    if username:
        username_label = f"@{username}"
        if display_name == username_label:
            return username_label
        return f"{display_name} ({username_label})"

    user_id = sender.get("user_id")
    if user_id and display_name != f"ID {user_id}":
        return f"{display_name} (ID {user_id})"
    return display_name


def is_secret_sender(data: dict, user) -> bool:
    sender = data.get("sender") or {}
    return bool(user and sender.get("user_id") == user.id)


def id_answer_name(user) -> str:
    username = normalize_username(user.username or "")
    return user.full_name or user.first_name or (f"@{username}" if username else "İstifadəçi")


def format_user_id_answer(name: str, user_id: int) -> str:
    return f"{name} adlı istifadəçinin ID-si {user_id}."


def raw_user_name(user_data: dict) -> str:
    first_name = (user_data.get("first_name") or "").strip()
    last_name = (user_data.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    username = normalize_username(user_data.get("username") or "")
    return full_name or (f"@{username}" if username else "İstifadəçi")


def raw_replied_user_from_api_kwargs(message):
    raw_reply = message.api_kwargs.get("reply_to_message")
    if isinstance(raw_reply, dict):
        raw_user = raw_reply.get("from")
        if isinstance(raw_user, dict) and raw_user.get("id"):
            return raw_user_name(raw_user), raw_user["id"]

    external_reply = message.api_kwargs.get("external_reply")
    if not isinstance(external_reply, dict):
        return None

    origin = external_reply.get("origin")
    if not isinstance(origin, dict):
        return None

    sender_user = origin.get("sender_user")
    if isinstance(sender_user, dict) and sender_user.get("id"):
        return raw_user_name(sender_user), sender_user["id"]

    return None


def remember_user(user):
    if not user:
        return

    display_name = user_display_name(user)
    USER_NAMES_BY_ID[str(user.id)] = display_name

    username = normalize_username(user.username or "")
    if username:
        USER_NAMES_BY_USERNAME[username] = display_name


def apply_known_display_name(target: dict):
    if target.get("display_name"):
        return target

    if target["type"] == "id":
        target["display_name"] = USER_NAMES_BY_ID.get(target["value"])
    elif target["type"] == "username":
        target["display_name"] = USER_NAMES_BY_USERNAME.get(target["value"])

    return target


def make_username_target(value: str):
    username = normalize_username(value)
    if not USERNAME_RE.fullmatch(username):
        return None

    return {
        "type": "username",
        "value": username,
        "key": f"username:{username}",
        "display_name": USER_NAMES_BY_USERNAME.get(username),
    }


def make_id_target(value: str):
    if not USER_ID_RE.fullmatch(value.strip()):
        return None

    user_id = int(value.strip())
    if user_id <= 0:
        return None

    normalized_id = str(user_id)
    return {
        "type": "id",
        "value": normalized_id,
        "user_id": user_id,
        "key": f"id:{normalized_id}",
        "display_name": USER_NAMES_BY_ID.get(normalized_id),
    }


def make_reply_target(user):
    remember_user(user)

    username = normalize_username(user.username or "")
    if username:
        target = make_username_target(username)
        if target:
            target["display_name"] = user_display_name(user)
            target["aliases"] = [f"id:{user.id}"]
            return target

    target = make_id_target(str(user.id))
    if not target and user.id > 0:
        normalized_id = str(user.id)
        target = {
            "type": "id",
            "value": normalized_id,
            "user_id": user.id,
            "key": f"id:{normalized_id}",
            "display_name": None,
        }

    if target:
        target["display_name"] = user_display_name(user)
    return target


def parse_target_token(token: str, allow_bare_username: bool = False):
    cleaned = token.strip().strip(",")
    if not cleaned:
        return None

    id_target = make_id_target(cleaned)
    if id_target:
        return id_target

    if cleaned.startswith("@") or allow_bare_username:
        return make_username_target(cleaned)

    return None


def split_target_items(value: str):
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [item.strip() for item in value.split() if item.strip()]


def target_display_name(target: dict) -> str:
    if target["type"] == "id":
        return f"({target['value']})"

    return f"(@{target['value']})"


def summarize_targets(targets, limit: int = 3) -> str:
    labels = [target_display_name(target) for target in targets[:limit]]
    if len(targets) > limit:
        labels.append(f"və daha {len(targets) - limit} nəfər")
    return ", ".join(labels)


def user_target_keys(user) -> set:
    keys = {f"id:{user.id}"}
    username = normalize_username(user.username or "")
    if username:
        keys.add(f"username:{username}")
    return keys


def target_matches_user(target: dict, user_keys: set) -> bool:
    keys = {target["key"]}
    keys.update(target.get("aliases", []))
    return bool(keys & user_keys)


def secret_reader_limit(data: dict) -> int:
    if data.get("open_to_anyone"):
        return max(int(data.get("reader_limit") or 1), 1)
    return max(len(data["targets"]), 1)


def build_open_keyboard(data: dict):
    if data["status"] != "active":
        return None
    if len(data["read_by"]) >= secret_reader_limit(data):
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👁 Mesajı aç", callback_data=f"open|{data['id']}")]]
    )


def keyboard_args(data: dict):
    return {"re" + "ply_markup": build_open_keyboard(data)}


def url_keyboard(button_text: str, url: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton(button_text, url=url)]])


def bot_private_url(bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start=gizli"


def chat_public_url(chat) -> str:
    username = normalize_username(getattr(chat, "username", "") or "")
    if username:
        return f"https://t.me/{username}"
    return ""


def message_link(message) -> str:
    try:
        return message.link or ""
    except Exception:
        return ""


async def group_return_url(context: ContextTypes.DEFAULT_TYPE, sent_message) -> str:
    link = message_link(sent_message) or chat_public_url(sent_message.chat)
    if link:
        return link

    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=sent_message.chat_id,
            name="Gizli mesaja qayidis",
        )
        return invite.invite_link
    except Exception as exc:
        print(f"Qrup keçid linki yaradılmadı: {exc}")
        return ""


def create_secret_data(
    targets,
    message: str,
    duration=None,
    duration_text=None,
    sender=None,
    open_to_anyone: bool = False,
    reader_limit: int = None,
):
    secret_id = str(uuid.uuid4())
    created_at = now_local()
    expires_at = created_at + duration if duration else None

    unique_targets = {}
    for target in targets:
        apply_known_display_name(target)
        unique_targets.setdefault(target["key"], target)

    data = {
        "id": secret_id,
        "targets": list(unique_targets.values()),
        "secret": message[:4000],
        "duration_text": duration_text,
        "sender": make_sender_info(sender),
        "open_to_anyone": open_to_anyone,
        "reader_limit": max(int(reader_limit or len(unique_targets) or 1), 1),
        "created_at": created_at,
        "expires_at": expires_at,
        "reads": [],
        "read_by": set(),
        "status": "active",
        "inline_message_id": None,
        "chat_id": None,
        "message_id": None,
    }
    SECRETS[secret_id] = data
    return data


def parse_duration(token: str):
    match = DURATION_RE.fullmatch(token.strip())
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if amount <= 0:
        return None

    if unit == "s":
        return timedelta(seconds=amount), f"{amount} saniyə"
    if unit in {"d", "m"}:
        return timedelta(minutes=amount), f"{amount} dəqiqə"
    if unit == "h":
        return timedelta(hours=amount), f"{amount} saat"

    return None


def parse_targets(raw_targets: str):
    cleaned = raw_targets.strip()
    if cleaned.startswith("(") and ")" in cleaned:
        closing_index = cleaned.find(")")
        inside = cleaned[1:closing_index]
        rest = cleaned[closing_index + 1 :].strip()
        targets = [parse_target_token(item) for item in split_target_items(inside)]
        if not targets or any(target is None for target in targets):
            return None, None
        return targets, rest

    targets = []
    position = 0
    while position < len(cleaned):
        match = re.match(r"\s*(@[A-Za-z0-9_]{3,64}|\d{8,12})(?=$|[\s,])", cleaned[position:])
        if not match:
            break

        target = parse_target_token(match.group(1))
        if not target:
            break

        targets.append(target)
        position += match.end()

        while position < len(cleaned) and cleaned[position].isspace():
            position += 1
        if position < len(cleaned) and cleaned[position] == ",":
            position += 1
            while position < len(cleaned) and cleaned[position].isspace():
                position += 1

    if targets:
        message = cleaned[position:].strip()
        if message:
            return targets, message

    return None, None


def parse_public_inline_message(text: str):
    cleaned = text.strip()
    if not cleaned:
        return None

    reader_limit = 1
    message = cleaned
    parts = cleaned.split(" ", 1)

    if (
        len(parts) == 2
        and PUBLIC_READER_LIMIT_RE.fullmatch(parts[0])
        and 1 <= int(parts[0]) <= 99
    ):
        reader_limit = int(parts[0])
        message = parts[1].strip()

    if not message:
        return None

    return {
        "targets": [],
        "message": message[:4000],
        "open_to_anyone": True,
        "reader_limit": reader_limit,
    }


def parse_inline_payload(query_text: str):
    text = query_text.strip()
    if not text:
        return None

    parts = text.split(" ", 1)
    duration = None
    duration_text = None
    remaining = text

    if len(parts) > 1:
        parsed_duration = parse_duration(parts[0])
        if parsed_duration:
            duration, duration_text = parsed_duration
            remaining = parts[1].strip()

    targets, message = parse_targets(remaining)
    if not targets or not message:
        public_message = parse_public_inline_message(remaining)
        if not public_message:
            return None

        public_message.update(
            {
                "duration": duration,
                "duration_text": duration_text,
            }
        )
        return public_message

    unique_targets = {}
    for target in targets:
        unique_targets.setdefault(target["key"], target)

    if not unique_targets:
        return None

    return {
        "targets": list(unique_targets.values()),
        "message": message[:4000],
        "duration": duration,
        "duration_text": duration_text,
        "open_to_anyone": False,
        "reader_limit": len(unique_targets),
    }


def parse_reply_options(tokens):
    duration = None
    duration_text = None
    leaked_text = ""

    if not tokens:
        return {
            "duration": duration,
            "duration_text": duration_text,
            "leaked_text": leaked_text,
        }

    parsed_duration = parse_duration(tokens[0])
    if parsed_duration:
        duration, duration_text = parsed_duration
        leaked_text = " ".join(tokens[1:]).strip()
    else:
        leaked_text = " ".join(tokens).strip()

    return {
        "duration": duration,
        "duration_text": duration_text,
        "leaked_text": leaked_text,
    }


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME

    if BOT_USERNAME:
        return BOT_USERNAME

    me = await context.bot.get_me()
    BOT_USERNAME = me.username
    return BOT_USERNAME


def extract_reply_mention_payload(message_text: str, bot_username: str):
    if not message_text or not bot_username:
        return None

    text = message_text.strip()
    prefix = f"@{bot_username}"
    prefix_len = len(prefix)

    if text.lower() == prefix.lower():
        return ""

    if not text.lower().startswith(prefix.lower()):
        return None

    separator = text[prefix_len : prefix_len + 1]
    if separator and not (separator.isspace() or separator in {":", ",", "-"}):
        return None

    payload = text[prefix_len:].strip()
    if payload[:1] in {":", ",", "-"}:
        payload = payload[1:].strip()

    return payload


def build_usage_hint_result():
    return InlineQueryResultArticle(
        id="usage-help",
        title="Gizli mesaj yaz",
        description="Mesajı ilk 1 nəfər və ya yazdığın say qədər adam aça bilər.",
        input_message_content=InputTextMessageContent(
            "Inline gizli mesaj üçün mətn yaz.\n\n"
            "Düzgün nümunələr:\n"
            "@ZiyaGizliBot salam\n"
            "@ZiyaGizliBot 3 salam\n"
            "@ZiyaGizliBot @istifadeciadi salam\n"
            "@ZiyaGizliBot 7823137189 salam\n"
            "@ZiyaGizliBot 1h @istifadeciadi salam\n"
            "@ZiyaGizliBot 7823137189 1234567890 9876543210 salam\n"
            "@ZiyaGizliBot (@istifadeciadi, 7823137189) salam"
        ),
    )


def build_message_text(data: dict) -> str:
    total = secret_reader_limit(data)
    read_count = len(data["read_by"])
    recipient_line = None
    target_line = None

    if data.get("open_to_anyone"):
        recipient_line = None
    elif total == 1:
        recipient_line = f"👤 Alıcı: {target_display_name(data['targets'][0])}"
    else:
        recipient_line = f"👥 Alıcılar: {total} nəfər"
        target_line = f"🎯 Hədəflər: {summarize_targets(data['targets'])}"

    created_line = f"🕒 Göndərilmə: {format_clock(data['created_at'])} ({BAKU_TIME_LABEL})"

    if data["status"] == "expired":
        summary_line = "⌛ Bu mesajın vaxtı bitdiyi üçün artıq açıla bilməz."
    elif data.get("open_to_anyone") and (data["status"] == "consumed" or read_count >= total):
        summary_line = "🔐 Mesaj bağlanıb."
    elif data.get("open_to_anyone"):
        summary_line = "🔓 Mesajı açmaq olar."
    elif total == 1 and read_count >= 1:
        summary_line = "👁 Oxundu."
    elif total > 1 and read_count == total:
        summary_line = "✅ Bütün alıcılar mesajı oxuyub."
    elif read_count > 0:
        summary_line = f"👁 Oxunma: {read_count}/{total}"
    else:
        summary_line = "🔐 Mesaj hələ açılmayıb."

    lines = []
    if data.get("sender"):
        lines.append(f"✍️ Göndərən: {sender_display_name(data['sender'])}")

    if recipient_line:
        lines.append(recipient_line)
    if target_line:
        lines.append(target_line)

    lines.append(created_line)
    if data["expires_at"]:
        lines.append(f"⏳ Vaxt limiti: {data['duration_text']}")
    lines.append(summary_line)

    if data["reads"]:
        lines.append("")
        for read in data["reads"]:
            lines.append(f"• {read['display_name']} - {format_clock(read['read_at'])} ({BAKU_TIME_LABEL})")

    if data["status"] == "expired":
        lines.append("")
        lines.append("⚠️ Məzmun qorunub, amma vaxt bitdiyi üçün açılmır.")

    return "\n".join(lines)


async def refresh_secret_message(context: ContextTypes.DEFAULT_TYPE, data: dict):
    inline_message_id = data.get("inline_message_id")
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    if not inline_message_id and not (chat_id and message_id):
        return

    try:
        if inline_message_id:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=build_message_text(data),
                **keyboard_args(data),
            )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=build_message_text(data),
                **keyboard_args(data),
            )
    except Exception:
        pass


async def expire_secret(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job:
        return

    secret_id = job.data.get("secret_id")
    data = SECRETS.get(secret_id)
    if not data or data["status"] != "active":
        return

    data["status"] = "expired"
    await refresh_secret_message(context, data)


def schedule_secret_expiration(context: ContextTypes.DEFAULT_TYPE, data: dict):
    if not data["expires_at"] or not context.job_queue:
        return

    delay = max((data["expires_at"] - now_local()).total_seconds(), 0)
    context.job_queue.run_once(
        expire_secret,
        when=delay,
        data={"secret_id": data["id"]},
        name=f"expire-{data['id']}",
    )


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.inline_query.from_user)

    q = update.inline_query.query.strip()
    if not q:
        await update.inline_query.answer([build_usage_hint_result()], cache_time=0)
        return

    parsed = parse_inline_payload(q)
    if not parsed:
        await update.inline_query.answer([build_usage_hint_result()], cache_time=0)
        return

    target_label = summarize_targets(parsed["targets"])
    data = create_secret_data(
        parsed["targets"],
        parsed["message"],
        duration=parsed["duration"],
        duration_text=parsed["duration_text"],
        sender=update.inline_query.from_user,
        open_to_anyone=parsed.get("open_to_anyone", False),
        reader_limit=parsed.get("reader_limit"),
    )

    if parsed.get("open_to_anyone"):
        description = f"İlk {parsed['reader_limit']} nəfər aça bilər"
    else:
        description = f"{len(parsed['targets'])} alıcı üçün gizli mesaj"
        if len(parsed["targets"]) == 1:
            description = f"{target_label} üçün gizli mesaj"
    if parsed["duration_text"]:
        description += f" • {parsed['duration_text']}"

    result = InlineQueryResultArticle(
        id=data["id"],
        title="🔒 Gizli mesaj",
        description=description,
        input_message_content=InputTextMessageContent(build_message_text(data)),
        **keyboard_args(data),
    )

    await update.inline_query.answer([result], cache_time=0)


async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    remember_user(result.from_user)

    data = SECRETS.get(result.result_id)
    if not data:
        return

    data["inline_message_id"] = result.inline_message_id

    schedule_secret_expiration(context, data)


async def try_delete_message(message):
    try:
        await message.delete()
    except Exception as exc:
        print(f"Mesaj silinmədi: {exc}")


def pending_prompt_text(pending: dict, leaked_text: str = "") -> str:
    lines = [
        "Gizli mesaj mətnini indi buraya yaz.",
        f"Alıcı: {target_display_name(pending['target'])}",
    ]

    if pending.get("duration_text"):
        lines.append(f"Vaxt limiti: {pending['duration_text']}")

    if leaked_text:
        lines.extend(
            [
                "",
                "Qrupda yazdığın mətn istifadə olunmadı.",
                "Gizli qalması üçün mətni yalnız bu şəxsi söhbətdə göndər.",
            ]
        )

    lines.append("")
    lines.append("Ləğv etmək üçün /cancel yaz.")
    return "\n".join(lines)


async def send_pending_prompt(context: ContextTypes.DEFAULT_TYPE, user_id: int, leaked_text: str = ""):
    pending = PENDING_REPLY_SECRETS.get(user_id)
    if not pending:
        return False

    await context.bot.send_message(
        chat_id=user_id,
        text=pending_prompt_text(pending, leaked_text),
    )
    return True


async def send_bot_transition_button(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    reply_to_message_id: int,
):
    bot_username = await get_bot_username(context)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Gizli mesaj mətnini botun şəxsi söhbətində yaz.",
        reply_to_message_id=reply_to_message_id,
        allow_sending_without_reply=True,
        reply_markup=url_keyboard("Bota keçid", bot_private_url(bot_username)),
    )


async def reply_with_group_transition(message, context: ContextTypes.DEFAULT_TYPE, sent_message):
    link = await group_return_url(context, sent_message)
    if link:
        await message.reply_text(
            "Gizli mesaj qrupa göndərildi.",
            reply_markup=url_keyboard("Qrupa keçid", link),
        )
        return

    await message.reply_text(
        "Gizli mesaj qrupa göndərildi, amma bu qrup üçün keçid linki yarada bilmədim."
    )


async def begin_reply_secret_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tokens,
    usage_text: str,
):
    message = update.effective_message
    if not message:
        return

    if not message.reply_to_message:
        await message.reply_text(REPLY_SECRET_NO_REPLY_TEXT)
        return

    remember_user(message.from_user)

    options = parse_reply_options(tokens)
    if options["leaked_text"]:
        await try_delete_message(message)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=REPLY_SECRET_EXTRA_TEXT_ERROR,
            reply_to_message_id=message.reply_to_message.message_id,
            allow_sending_without_reply=True,
        )
        return

    replied_user = message.reply_to_message.from_user
    if not replied_user:
        await message.reply_text(
            "Reply olunan mesajda istifadəçi tapılmadı. Alıcını username və ya ID ilə yaz."
        )
        return

    target = make_reply_target(replied_user)
    if not target:
        await message.reply_text(
            "Reply olunan istifadəçini alıcı kimi tanımaq mümkün olmadı."
        )
        return

    user_id = message.from_user.id
    PENDING_REPLY_SECRETS[user_id] = {
        "chat_id": update.effective_chat.id,
        "reply_to_message_id": message.reply_to_message.message_id,
        "target": target,
        "duration": options["duration"],
        "duration_text": options["duration_text"],
        "created_at": now_local(),
    }

    await try_delete_message(message)

    transition_sent = False
    try:
        await send_bot_transition_button(
            context,
            update.effective_chat.id,
            message.reply_to_message.message_id,
        )
        transition_sent = True
    except Exception as exc:
        print(f"Bota keçid düyməsi göndərilmədi: {exc}")

    try:
        await send_pending_prompt(context, user_id, options["leaked_text"])
    except Exception as exc:
        bot_username = await get_bot_username(context)
        print(f"Şəxsi mesaj göndərilmədi: {exc}")
        if not transition_sent:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Gizli mətni qrupda yazma. Əvvəlcə @{bot_username}-a start ver.",
                reply_to_message_id=message.reply_to_message.message_id,
                allow_sending_without_reply=True,
                reply_markup=url_keyboard("Bota keçid", bot_private_url(bot_username)),
            )


async def finish_pending_reply_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text:
        return

    pending = PENDING_REPLY_SECRETS.get(user.id)
    if not pending:
        return

    secret_text = message.text.strip()
    if not secret_text:
        await message.reply_text("Boş mesaj göndərmə. Gizli mətni yaz və göndər.")
        return

    data = create_secret_data(
        [pending["target"]],
        secret_text,
        duration=pending["duration"],
        duration_text=pending["duration_text"],
        sender=user,
    )

    try:
        sent_message = await context.bot.send_message(
            chat_id=pending["chat_id"],
            text=build_message_text(data),
            reply_to_message_id=pending["reply_to_message_id"],
            allow_sending_without_reply=True,
            **keyboard_args(data),
        )
    except Exception as exc:
        print(f"Gizli mesaj qrupa göndərilmədi: {exc}")
        await message.reply_text("Gizli mesajı qrupa göndərə bilmədim. Botun qrupda olduğuna və yazma icazəsinə bax.")
        return

    data["chat_id"] = sent_message.chat_id
    data["message_id"] = sent_message.message_id
    schedule_secret_expiration(context, data)
    PENDING_REPLY_SECRETS.pop(user.id, None)

    await reply_with_group_transition(message, context, sent_message)


async def reply_secret_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await begin_reply_secret_flow(update, context, context.args, "/gizli")


async def reply_secret_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    bot_username = await get_bot_username(context)
    payload_text = extract_reply_mention_payload(message.text, bot_username)
    if payload_text is None:
        return

    await begin_reply_secret_flow(
        update,
        context,
        payload_text.split(),
        f"@{bot_username}",
    )


async def open_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        _, secret_id = query.data.split("|", 1)
    except Exception:
        secret_id = None

    data = SECRETS.get(secret_id)
    if not data:
        await query.answer("Mesaj tapılmadı və ya artıq silinib. ❌", show_alert=True)
        return

    user = query.from_user
    remember_user(user)

    if data["status"] == "expired" or (data["expires_at"] and now_local() >= data["expires_at"]):
        data["status"] = "expired"
        await refresh_secret_message(context, data)
        await query.answer(
            "Bu mesajın vaxtı bitdiyi üçün artıq açıla bilməz. ⌛",
            show_alert=True,
        )
        return

    if is_secret_sender(data, user):
        await query.answer("Öz göndərdiyin mesajı aça bilməzsən. 🔐", show_alert=True)
        return

    if data.get("open_to_anyone"):
        matched_targets = []
        matched_keys = {f"id:{user.id}"}

        if matched_keys.issubset(data["read_by"]):
            await query.answer("Bu mesajı artıq oxumusan. Təkrar açmaq olmur. 🔐", show_alert=True)
            return

        if data["status"] == "consumed" or len(data["read_by"]) >= secret_reader_limit(data):
            data["status"] = "consumed"
            await refresh_secret_message(context, data)
            await query.answer("Bu mesaj artıq oxunma limitinə çatıb. 🔐", show_alert=True)
            return
    else:
        keys = user_target_keys(user)
        matched_targets = [target for target in data["targets"] if target_matches_user(target, keys)]
        matched_keys = {target["key"] for target in matched_targets}

        if not matched_targets:
            await query.answer("Bu mesaj sənə aid deyil. Açmaq mümkün deyil. 🔒", show_alert=True)
            return

        if matched_keys.issubset(data["read_by"]):
            await query.answer("Bu mesajı artıq oxumusan. Təkrar açmaq olmur. 🔐", show_alert=True)
            return

    read_at = now_local()
    username = normalize_username(user.username or "")
    display_name = user_display_name(user)

    for target in matched_targets:
        target["display_name"] = display_name

    data["read_by"].update(matched_keys)
    data["reads"].append(
        {
            "username": username,
            "user_id": user.id,
            "display_name": display_name,
            "targets": [target_display_name(target) for target in matched_targets],
            "read_at": read_at,
        }
    )

    if len(data["read_by"]) >= secret_reader_limit(data):
        data["status"] = "consumed"

    await query.answer(
        data["secret"],
        show_alert=True,
    )

    await refresh_secret_message(context, data)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    if update.effective_chat.type == "private" and update.effective_user.id in PENDING_REPLY_SECRETS:
        await send_pending_prompt(context, update.effective_user.id)
        return

    await context.bot.send_message(chat_id=update.effective_chat.id, text=START_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=HELP_TEXT)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update.effective_user)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=ABOUT_TEXT)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return

    remember_user(user)

    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        if replied_user:
            remember_user(replied_user)
            await message.reply_text(format_user_id_answer(id_answer_name(replied_user), replied_user.id))
            return

        sender_chat = message.reply_to_message.sender_chat
        if sender_chat:
            await message.reply_text(
                f"{sender_chat.title} adlı chatın ID-si {sender_chat.id}."
            )
            return

        await message.reply_text("Reply olunan mesajda istifadəçi ID-si tapılmadı.")
        return

    raw_replied_user = raw_replied_user_from_api_kwargs(message)
    if raw_replied_user:
        name, replied_user_id = raw_replied_user
        await message.reply_text(format_user_id_answer(name, replied_user_id))
        return

    if update.effective_chat.type != "private":
        await message.reply_text(
            "Reply olunan istifadəçini görə bilmədim. "
            "Kimin ID-sini istəyirsənsə, onun mesajına yanıt verib /id yaz."
        )
        print(f"/id reply məlumatı gəlmədi. api_kwargs={dict(message.api_kwargs)}")
        return

    await message.reply_text(f"Sənin ID-in {user.id}.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if PENDING_REPLY_SECRETS.pop(user.id, None):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Gizli mesaj ləğv edildi.")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Aktiv gizli mesaj gözləntisi yoxdur.")


async def post_init(app):
    global BOT_USERNAME

    me = await app.bot.get_me()
    BOT_USERNAME = me.username
    try:
        await app.bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
        await app.bot.set_my_description(BOT_DESCRIPTION)
    except Exception as exc:
        print(f"Bot haqqında məlumat yenilənmədi: {exc}")
    print(f"Bot başladı: @{me.username}")


def main():
    token = get_bot_token()
    if not token:
        return

    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )

    app = (
        ApplicationBuilder()
        .token(token)
        .request(request)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("gizli", reply_secret_command))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, finish_pending_reply_secret))
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY & filters.ChatType.GROUPS & ~filters.COMMAND, reply_secret_mention))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(open_secret, pattern=r"^open\|"))
    app.add_handler(ChosenInlineResultHandler(chosen_inline_result))

    ensure_event_loop()
    print("🤖 Bot işləyir...")
    app.run_polling()


if __name__ == "__main__":
    main()
