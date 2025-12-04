import os
import json
import time

DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

_users = None
_config = None


def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def _load_json(path, default):
    ensure_data_dir()
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    ensure_data_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def init_db():
    global _users, _config
    if _users is None:
        _users = _load_json(USERS_FILE, {})
    if _config is None:
        _config = _load_json(
            CONFIG_FILE,
            {
                "second_prefix": None,
                "logs": {},
                "games_enabled": True,
                "claim": {
                    "enabled": False,
                    "amount": 0,
                    "expires_at": 0,
                    "claimed_users": [],
                },
            },
        )


def get_users():
    global _users
    if _users is None:
        init_db()
    return _users


def save_users():
    global _users
    if _users is None:
        _users = {}
    _save_json(USERS_FILE, _users)


def get_config():
    global _config
    if _config is None:
        init_db()

    _config.setdefault("second_prefix", None)
    _config.setdefault("logs", {})
    _config.setdefault("games_enabled", True)

    if "claim" not in _config or not isinstance(_config["claim"], dict):
        _config["claim"] = {
            "enabled": False,
            "amount": 0,
            "expires_at": 0,
            "claimed_users": [],
        }
    else:
        c = _config["claim"]
        c.setdefault("enabled", False)
        c.setdefault("amount", 0)
        c.setdefault("expires_at", 0)
        c.setdefault("claimed_users", [])

    return _config


def save_config():
    global _config
    if _config is None:
        _config = {
            "second_prefix": None,
            "logs": {},
            "games_enabled": True,
            "claim": {
                "enabled": False,
                "amount": 0,
                "expires_at": 0,
                "claimed_users": [],
            },
        }
    _save_json(CONFIG_FILE, _config)


# ========== PROFILES ==========


def get_profile(user_id: int):
    """Return a user profile dict, always with all required keys."""
    users = get_users()
    uid = str(user_id)

    # NEW PROFILE
    if uid not in users:
        users[uid] = {
            # economy
            "cash": 250000,
            "daily_last": 0,

            # daily streak system
            "daily_streak": 0,  # current streak
            "best_streak": 0,  # best streak record

            # profile
            "about": "",
            "rings": {
                "1": 0,
                "2": 0,
                "3": 0,
            },
            "married_to": None,
            "ring_id": None,
            "marriages": 0,
            "marry_request_from": None,
            "marry_request_ring": None,

            # cosmetics
            "backgrounds": {},  # bg1/bg2/bg3 counts
            "active_bg": None,  # selected bg id
            "banner_url": None,  # profile banner image url

            # level system
            "level": 0,
            "xp": 0,
            "total_xp": 0,

            # blackjack stats
            "bj_games": 0,
            "bj_wins": 0,
            "bj_losses": 0,
            "bj_pushes": 0,
            "bj_profit": 0,

            # user-vs-user coinflip stats
            "cf_games": 0,
            "cf_wins": 0,
            "cf_losses": 0,
            "cf_profit": 0,

            # crash game stats
            "crash_games": 0,
            "crash_profit": 0,

            # trivia stats
            "trivia_correct": 0,
            "trivia_wrong": 0,

            # gifts
            "gift_sent": 0,
            "gift_received": 0,

            # family system
            "family_id": None,  # id of family / gang / clan
            "family_role": None,  # e.g. 'owner', 'member'
        }

    # EXISTING PROFILE → ensure all keys (safe upgrade for old users)
    else:
        p = users[uid]

        # economy
        if "cash" not in p:
            p["cash"] = p.get("balance", 250000)
        if "daily_last" not in p:
            p["daily_last"] = 0

        # streak
        p.setdefault("daily_streak", 0)
        p.setdefault("best_streak", 0)

        # profile basics
        if "about" not in p:
            p["about"] = ""
        if "rings" not in p:
            p["rings"] = {"1": 0, "2": 0, "3": 0}
        else:
            for rid in ("1", "2", "3"):
                p["rings"].setdefault(rid, 0)
        if "married_to" not in p:
            p["married_to"] = None
        if "ring_id" not in p:
            p["ring_id"] = None
        if "marriages" not in p:
            p["marriages"] = 0
        if "marry_request_from" not in p:
            p["marry_request_from"] = None
        if "marry_request_ring" not in p:
            p["marry_request_ring"] = None

        # cosmetics
        if "backgrounds" not in p or p["backgrounds"] is None:
            p["backgrounds"] = {}
        if "active_bg" not in p:
            p["active_bg"] = None
        if "banner_url" not in p:
            p["banner_url"] = None

        # level system
        p.setdefault("level", 0)
        p.setdefault("xp", 0)
        p.setdefault("total_xp", 0)

        # blackjack stats
        p.setdefault("bj_games", 0)
        p.setdefault("bj_wins", 0)
        p.setdefault("bj_losses", 0)
        p.setdefault("bj_pushes", 0)
        p.setdefault("bj_profit", 0)

        # user-vs-user coinflip stats
        p.setdefault("cf_games", 0)
        p.setdefault("cf_wins", 0)
        p.setdefault("cf_losses", 0)
        p.setdefault("cf_profit", 0)

        # crash game stats
        p.setdefault("crash_games", 0)
        p.setdefault("crash_profit", 0)

        # trivia stats
        p.setdefault("trivia_correct", 0)
        p.setdefault("trivia_wrong", 0)

        # gifts
        p.setdefault("gift_sent", 0)
        p.setdefault("gift_received", 0)

        # family system
        p.setdefault("family_id", None)
        p.setdefault("family_role", None)

    return users[uid]


# ========== PREFIX & LOGS ==========


def get_second_prefix():
    cfg = get_config()
    return cfg.get("second_prefix")


def set_second_prefix(prefix):
    cfg = get_config()
    cfg["second_prefix"] = prefix
    save_config()


def get_log_channel(log_type: str):
    cfg = get_config()
    logs = cfg.get("logs", {})
    return logs.get(log_type)


def set_log_channel(log_type: str, channel_id: int):
    cfg = get_config()
    logs = cfg.setdefault("logs", {})
    logs[log_type] = int(channel_id)
    save_config()


# ========== GAMES ON/OFF ==========


def are_games_enabled() -> bool:
    cfg = get_config()
    return cfg.get("games_enabled", True)


def set_games_enabled(enabled: bool):
    cfg = get_config()
    cfg["games_enabled"] = bool(enabled)
    save_config()


# ========== CLAIM EVENT ==========


def set_claim(amount: int, duration_seconds: int = 24 * 60 * 60):
    cfg = get_config()
    now = time.time()
    cfg["claim"]["enabled"] = True
    cfg["claim"]["amount"] = int(amount)
    cfg["claim"]["expires_at"] = now + duration_seconds
    cfg["claim"]["claimed_users"] = []
    save_config()


def disable_claim():
    cfg = get_config()
    cfg["claim"]["enabled"] = False
    save_config()


def get_claim_config():
    cfg = get_config()
    return cfg["claim"]
