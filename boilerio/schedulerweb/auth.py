import os
import base64
import logging
from flask_login import UserMixin
from hashlib import scrypt

from . import model, util

logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------
# Device authentication

def make_salt() -> bytes:
    return os.urandom(16)


def hash_password(password: str, salt: bytes) -> bytes:
    """Returns a base64-encoded secure hash of the supplied password."""
    # Scrypt parameters  were selected based on suggestions here:
    # https://cryptobook.nakov.com/mac-and-key-derivation/scrypt
    SCRYPT_N = 16384
    SCRYPT_R = 8
    SCRYPT_P = 1
    h = scrypt(password.encode('utf-8'), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.b64encode(h)


class Device(UserMixin):
    def __init__(self):
        self.id = "DEVICE"


# ---------------------------------------------------------------------
# Human authentication

class User(UserMixin):
    def __init__(self, ident, name, profile_pic):
        self.id = ident
        self.name = name
        self.profile_pic = profile_pic

    def update(self, name, profile_pic):
        self.name = name
        self.profile_pic = profile_pic


class UserManager(object):
    """Simple user manager class."""

    def __init__(self):
        self.known_users = {}

    def lookup_and_update_google_user(self, google_subscriber_id, name, email,
                                      profile_pic):
        """Add or update user profile info."""
        db = util.get_db()

        user = model.UserIdentity.lookup_user_by_google_id(db, google_subscriber_id)
        if user is None:
            logging.info("Reject login request for Google subscriber ID %s",
                        google_subscriber_id)
            return None

        user.update(db, name, email, profile_pic)
        db.commit()
        return User(user.user_id, user.name, user.picture)

    def lookup_user(self, user_id):
        """Lookup user by ID.  Returns User object."""
        db = util.get_db()
        user = model.UserIdentity.lookup_user_by_internal_id(db, user_id)
        return User(user.user_id, user.name, user.picture)

