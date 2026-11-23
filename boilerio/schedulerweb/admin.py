"""Command-line administration for the BoilerIO backend database.

Run with the backend's settings file selected, as for the web application:

    BOILERIO_SETTINGS=/path/to/settings.cfg python -m boilerio.schedulerweb.admin add-user GOOGLE_ID
    BOILERIO_SETTINGS=/path/to/settings.cfg python -m boilerio.schedulerweb.admin add-device
"""

import argparse
import base64
import secrets
import sys

from flask import Config

from . import auth, model


def add_user(db, google_subscriber_id, name, email):
    """Allow a Google account to sign in; returns the new user ID."""
    if model.UserIdentity.lookup_user_by_google_id(db, google_subscriber_id) is not None:
        raise ValueError("A user with that Google subscriber ID already exists")
    cursor = db.cursor()
    cursor.execute(
        "insert into users (google_subscriber_id, name, email) "
        "values (%s, %s, %s) returning user_id",
        (google_subscriber_id, name, email))
    user_id = cursor.fetchone()[0]
    db.commit()
    return user_id


def add_device(db):
    """Create device credentials; returns (device ID, secret)."""
    secret = secrets.token_urlsafe(32)
    salt = auth.make_salt()
    cursor = db.cursor()
    cursor.execute(
        "insert into device (device_secret_hashed, salt) "
        "values (%s, %s) returning device_id",
        (auth.hash_password(secret, salt).decode(), base64.b64encode(salt).decode()))
    device_id = cursor.fetchone()[0]
    db.commit()
    return device_id, secret


def connect(settings):
    return model.db_connect(settings['DB_HOST'], settings['DB_NAME'],
                            settings['DB_USER'], settings['DB_PASSWORD'])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Administer the BoilerIO backend database. The settings "
                    "file is read from BOILERIO_SETTINGS.")
    commands = parser.add_subparsers(dest='command', required=True)

    user_parser = commands.add_parser(
        'add-user', help="Allow a Google account to sign in to the web UI")
    user_parser.add_argument(
        'google_subscriber_id',
        help="The account's Google subscriber ID. The backend logs it when "
             "an unknown account tries to sign in.")
    user_parser.add_argument('--name', default='',
                             help="Display name (updated from Google at sign-in)")
    user_parser.add_argument('--email', default='',
                             help="Email address (updated from Google at sign-in)")

    commands.add_parser(
        'add-device', help="Create credentials for a scheduler to use")

    args = parser.parse_args(argv)

    settings = Config('.')
    try:
        settings.from_envvar('BOILERIO_SETTINGS')
    except (RuntimeError, OSError) as e:
        sys.exit(str(e))
    db = connect(settings)
    try:
        if args.command == 'add-user':
            try:
                user_id = add_user(db, args.google_subscriber_id, args.name, args.email)
            except ValueError as e:
                sys.exit(str(e))
            print(f"Created user {user_id}")
        else:
            device_id, secret = add_device(db)
            print("Created device. Put these in the scheduler's [heating] "
                  "configuration; the secret cannot be shown again.")
            print(f"scheduler_username = {device_id}")
            print(f"scheduler_password = {secret}")
    finally:
        db.close()


if __name__ == '__main__':
    main()
