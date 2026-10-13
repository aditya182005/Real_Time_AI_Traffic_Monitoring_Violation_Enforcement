"""User accounts for the dashboard (no Streamlit imports).

Accounts live in a JSON file (``USERS_FILE``, default ``users.json`` in the
data folder). Only a salted PBKDF2 hash of each password is stored. Manage
accounts from the command line:

    python -m app.users add alice --role operator
    python -m app.users list
    python -m app.users passwd alice
    python -m app.users remove alice

Roles, from least to most access:

    viewer    read the dashboard, evidence, alerts and live view
    operator  also analyze footage, start/stop live cameras, send test SMS
    admin     also read the audit log and the system status page
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

from app import paths

ROLES = ("viewer", "operator", "admin")
RANK = {role: number for number, role in enumerate(ROLES)}

SCHEME = "pbkdf2_sha256"
ITERATIONS = 600_000        # OWASP's 2023 guidance for PBKDF2-HMAC-SHA256
MIN_PASSWORD_LENGTH = 10
USERNAME = re.compile(r"^[a-z0-9._@-]{1,64}$")


class UserError(ValueError):
    """A problem with an account request, worded for the person."""


# -- passwords --------------------------------------------------------------

def hash_password(password, iterations=None):
    iterations = iterations or ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations)

    return "$".join((
        SCHEME, str(iterations),
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    ))


def verify_password(password, stored):
    """True if ``password`` matches ``stored``. Never raises."""

    try:
        scheme, iterations, salt, expected = str(stored).split("$")

        if scheme != SCHEME:
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"),
            base64.b64decode(salt), int(iterations))

        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# -- the users file ----------------------------------------------------------

def users_file():
    configured = os.getenv("USERS_FILE", "").strip()

    return Path(configured).expanduser() if configured \
        else paths.DATA_DIR / "users.json"


def normalize_name(name):
    return str(name or "").strip().lower()


def load_users(path=None):
    """``{username: {"role": ..., "password_hash": ...}}``.

    A missing file means no accounts. A damaged file raises ``UserError``
    instead of being treated as empty, because "no accounts" would quietly
    switch the login mode.
    """

    path = Path(path) if path else users_file()

    if not path.is_file():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["users"]
        users = {}

        for name, entry in entries.items():
            if entry["role"] not in ROLES:
                raise ValueError(f"unknown role for {name}")

            users[normalize_name(name)] = {
                "role": entry["role"],
                "password_hash": str(entry["password_hash"]),
            }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise UserError(
            f"The users file {path} is damaged ({exc}). Fix or remove it."
        ) from exc

    return users


def save_users(users, path=None):
    path = Path(path) if path else users_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")

    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump({"users": users}, out, indent=2, sort_keys=True)

        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass  # Windows

        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass

        raise


def check_name(name):
    name = normalize_name(name)

    if not USERNAME.match(name):
        raise UserError(
            "A username is 1 to 64 letters, digits, dots, dashes, "
            "underscores or @.")

    return name


def check_password(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(
            f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")


def add_user(name, password, role="viewer", path=None, replace=False):
    name = check_name(name)
    check_password(password)

    if role not in ROLES:
        raise UserError(f"Role must be one of: {', '.join(ROLES)}.")

    users = load_users(path)

    if name in users and not replace:
        raise UserError(f"The user '{name}' already exists.")

    users[name] = {"role": role, "password_hash": hash_password(password)}
    save_users(users, path)

    return name


def remove_user(name, path=None):
    name = normalize_name(name)
    users = load_users(path)

    if name not in users:
        raise UserError(f"There is no user '{name}'.")

    if users[name]["role"] == "admin" and sum(
            u["role"] == "admin" for u in users.values()) == 1:
        raise UserError("That is the only admin; add another one first.")

    del users[name]
    save_users(users, path)


def set_password(name, password, path=None):
    name = normalize_name(name)
    check_password(password)
    users = load_users(path)

    if name not in users:
        raise UserError(f"There is no user '{name}'.")

    users[name]["password_hash"] = hash_password(password)
    save_users(users, path)


# A hash to check against when the username does not exist, so a wrong
# username and a wrong password take the same time.
_DECOY = None


def authenticate(name, password, path=None):
    """The user's role if the name and password are right, else None."""

    global _DECOY

    users = load_users(path)
    entry = users.get(normalize_name(name))

    if entry is None:
        if _DECOY is None:
            _DECOY = hash_password("decoy-password-never-valid")

        verify_password(password, _DECOY)

        return None

    return entry["role"] if verify_password(
        password, entry["password_hash"]) else None


def has_permission(role, permission):
    """``view`` (anyone), ``operate`` (operator, admin) or ``admin``."""

    needed = {"view": "viewer", "operate": "operator",
              "admin": "admin"}.get(permission)

    if needed is None or role not in RANK:
        return False

    return RANK[role] >= RANK[needed]


# -- command line -------------------------------------------------------------

def _ask_password(args):
    if args.password:
        return args.password

    first = getpass.getpass("Password: ")

    if first != getpass.getpass("Repeat it: "):
        raise UserError("The two passwords differ.")

    return first


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.users", description="Manage dashboard users.")
    parser.add_argument("--file", help="users file (default: USERS_FILE or "
                        "users.json in the data folder)")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="create a user")
    add.add_argument("name")
    add.add_argument("--role", choices=ROLES, default="viewer")
    add.add_argument("--password", help="avoid: it shows in shell history")

    password = commands.add_parser("passwd", help="change a password")
    password.add_argument("name")
    password.add_argument("--password", help="avoid: shell history")

    remove = commands.add_parser("remove", help="delete a user")
    remove.add_argument("name")

    commands.add_parser("list", help="show users and roles")

    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            name = add_user(args.name, _ask_password(args), args.role,
                            args.file)
            print(f"Created {name} ({args.role}).")
        elif args.command == "passwd":
            set_password(args.name, _ask_password(args), args.file)
            print("Password changed.")
        elif args.command == "remove":
            remove_user(args.name, args.file)
            print("Removed.")
        else:
            users = load_users(args.file)

            for name in sorted(users):
                print(f"{name:<30} {users[name]['role']}")

            if not users:
                print("No users yet. Add one with: "
                      "python -m app.users add NAME --role admin")
    except UserError as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
