import os
import base64
from flask_login import UserMixin
from hashlib import scrypt


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
    pass
