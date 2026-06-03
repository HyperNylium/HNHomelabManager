import re
import os
import json
import discord
import asyncio
import tempfile
from zoneinfo import ZoneInfo
from datetime import datetime, UTC


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() == "true"


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
POST_CHANNEL_ID = os.getenv("POST_CHANNEL_ID", "")
OWNER_ID = os.getenv("OWNER_ID", "")
MOD_IDS_RAW = os.getenv("MOD_IDS", "")
GUILD_ID = os.getenv("GUILD_ID", "")
SIMKL_CLIENT_ID = os.getenv("SIMKL_CLIENT_ID", "")

# linux
SETTINGS_DIR = os.getenv("SETTINGS_DIR", "/app/config")
REPORTS_DIR = os.getenv("REPORTS_DIR", "/data/reports")

# windows
# SETTINGS_DIR = os.getenv("SETTINGS_DIR", "appdata/config")
# REPORTS_DIR = os.getenv("REPORTS_DIR", "appdata/reports")

SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

TITLE_MATCH_MODE = os.getenv("TITLE_MATCH_MODE", "startswith")
TITLE_PATTERN = os.getenv("TITLE_PATTERN", "[MEDIA REQUEST]:")

TITLE_CASE_SENSITIVE = env_bool("TITLE_CASE_SENSITIVE", True)
ONLY_OPEN_THREADS = env_bool("ONLY_OPEN_THREADS", True)
OPEN_NOT_ARCHIVED = env_bool("OPEN_NOT_ARCHIVED", True)
OPEN_NOT_LOCKED = env_bool("OPEN_NOT_LOCKED", True)

FETCH_ARCHIVED_PUBLIC = env_bool("FETCH_ARCHIVED_PUBLIC", True)
FETCH_ARCHIVED_PRIVATE = env_bool("FETCH_ARCHIVED_PRIVATE", True)

INCLUDE_ATTACHMENTS = env_bool("INCLUDE_ATTACHMENTS", True)
INCLUDE_EMBED_URLS = env_bool("INCLUDE_EMBED_URLS", False)

MAX_MESSAGES_PER_THREAD = None
_max_messages_raw = os.getenv("MAX_MESSAGES_PER_THREAD", "").strip()
if _max_messages_raw != "":
    try:
        MAX_MESSAGES_PER_THREAD = int(_max_messages_raw)
    except Exception:
        MAX_MESSAGES_PER_THREAD = None

TZ = os.getenv("TZ", "").strip() or "UTC"
DONE_TAG_NAME = "done/added/closed"

settings_lock = asyncio.Lock()


def ensure_dirs() -> None:
    if not os.path.exists(SETTINGS_DIR):
        os.makedirs(SETTINGS_DIR, exist_ok=True)

    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR, exist_ok=True)


def save_json(path: str, data) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    tmp_file = None
    tmp_name = None

    try:
        tmp_file = tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8")
        json.dump(data, tmp_file, indent=2, ensure_ascii=False)
        tmp_file.flush()

        try:
            os.fsync(tmp_file.fileno())
        except OSError:
            pass

        tmp_name = tmp_file.name
        tmp_file.close()

        os.replace(tmp_name, path)

    finally:
        try:
            if tmp_file and not tmp_file.closed:
                tmp_file.close()
        except Exception:
            pass

        try:
            if tmp_name and os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


def read_settings_file() -> dict:
    ensure_dirs()

    if not os.path.exists(SETTINGS_FILE):
        return {}

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)

        if isinstance(raw, dict):
            return raw

        return {}

    except json.JSONDecodeError:
        backup = f"{SETTINGS_FILE}.bak"
        try:
            os.replace(SETTINGS_FILE, backup)
        except Exception:
            pass
        return {}

    except Exception:
        return {}


def write_settings_file(settings: dict) -> None:
    save_json(SETTINGS_FILE, settings)


async def load_settings() -> dict:
    async with settings_lock:
        return read_settings_file()


async def save_settings(settings: dict) -> None:
    async with settings_lock:
        write_settings_file(settings)


def parse_id_list(raw: str | None) -> list[int]:
    if raw is None:
        raw = ""
    raw = raw.strip()
    if raw == "":
        return []

    if raw.startswith("["):
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                ids = []
                for item in loaded:
                    try:
                        ids.append(int(str(item).strip()))
                    except Exception:
                        pass
                return ids
        except Exception:
            pass

    cleaned = raw.replace(";", ",").replace("\n", ",")
    parts = []
    for piece in cleaned.split(","):
        piece = piece.strip()
        if piece != "":
            parts.append(piece)

    ids = []
    for part in parts:
        try:
            ids.append(int(part))
        except Exception:
            pass

    return ids


MOD_IDS = parse_id_list(MOD_IDS_RAW)


def get_timezone():
    if ZoneInfo is None:
        return UTC

    try:
        return ZoneInfo(TZ)
    except Exception as err:
        print(f"could not load timezone TZ={TZ!r} ({err!r}). falling back to UTC.")
        return UTC


DISPLAY_TZ = get_timezone()
print(f"using display timezone: {DISPLAY_TZ} (from TZ={TZ!r})")


def format_date(dt: datetime, hour12: bool = False) -> str:
    if not dt:
        return "unknown-time"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    local = dt.astimezone(DISPLAY_TZ)
    if hour12:
        return local.strftime("%Y-%m-%d %I:%M:%S %p %Z")
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")


def to_utc(dt: datetime) -> str:
    if not dt:
        return "unknown-time"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC).isoformat()


def to_discord_timestamp(value) -> str:
    if not isinstance(value, str) or value == "":
        return "unknown-time"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return discord.utils.format_dt(parsed, "f")


def normalize_case(text: str) -> str:
    if TITLE_CASE_SENSITIVE:
        return text
    return text.lower()


def title_matches(title: str) -> bool:
    title_norm = normalize_case(title)
    pattern_norm = normalize_case(TITLE_PATTERN)

    match TITLE_MATCH_MODE:
        case "startswith":
            return title_norm.startswith(pattern_norm)

        case "contains":
            return pattern_norm in title_norm

        case "regex":
            flags = 0
            if not TITLE_CASE_SENSITIVE:
                flags = re.IGNORECASE
            return re.search(TITLE_PATTERN, title, flags=flags) is not None

    raise ValueError(f"Unknown TITLE_MATCH_MODE: {TITLE_MATCH_MODE}")


def is_open_thread(thread: discord.Thread) -> bool:
    if not ONLY_OPEN_THREADS:
        return True

    if OPEN_NOT_ARCHIVED and thread.archived:
        return False

    if OPEN_NOT_LOCKED and thread.locked:
        return False

    return True


def thread_has_done_tag(thread: discord.Thread) -> bool:
    applied_tags = thread.applied_tags

    for tag in applied_tags:
        tag_name = tag.name.strip().lower()
        if tag_name == DONE_TAG_NAME.lower():
            return True

    return False


def is_owner(interaction: discord.Interaction) -> bool:
    if OWNER_ID and str(interaction.user.id) == str(OWNER_ID):
        return True

    if interaction.guild and interaction.guild.owner_id == interaction.user.id:
        return True

    return False


def is_mod(interaction: discord.Interaction) -> bool:
    if is_owner(interaction):
        return True

    if interaction.user.id in MOD_IDS:
        return True

    return False


def mention(user: discord.abc.User) -> str:
    return f"<@{user.id}>"


def next_report_id(existing_map: dict) -> str:
    numeric = []
    for key in existing_map.keys():
        try:
            numeric.append(int(key))
        except Exception:
            pass

    if len(numeric) > 0:
        numeric.sort()
        return str(numeric[-1] + 1)

    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def report_path(report_id: str) -> str:
    return os.path.join(REPORTS_DIR, f"report_{report_id}.json")


def shorten(text, max_len: int) -> str:
    if text is None:
        return ""

    text = str(text)

    if len(text) <= max_len:
        return text

    if max_len <= 3:
        return text[:max_len]

    return f"{text[: max_len - 3]}..."
