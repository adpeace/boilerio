from .. import schedulerweb_auth

def test_make_salt():
    """make_salt should return at least 16 bytes of data.

    Each call should return a different value, and it should not throw
    exceptions.
    """
    salt1 = schedulerweb_auth.make_salt()
    salt2 = schedulerweb_auth.make_salt()

    assert salt1 != salt2
    assert len(salt1) >= 16
    assert len(salt2) >= 16


def test_hash_password():
    """hash_password should return different hashes for different input."""
    test_p1 = "hello"
    test_p2 = "bye"
    test_salt1 = schedulerweb_auth.make_salt()
    test_salt2 = schedulerweb_auth.make_salt()

    # Changing the salt changes the result:
    hash_salt1 = schedulerweb_auth.hash_password(test_p1, test_salt1)
    hash_salt2 = schedulerweb_auth.hash_password(test_p1, test_salt2)
    assert hash_salt1 != hash_salt2

    # Changing the password changes the result:
    hash_p1 = schedulerweb_auth.hash_password(test_p1, test_salt1)
    hash_p2 = schedulerweb_auth.hash_password(test_p2, test_salt1)
    assert hash_p1 != hash_p2

    # Changing neither produces the same result:
    hash_p1_again = schedulerweb_auth.hash_password(test_p1, test_salt1)
    assert hash_p1 == hash_p1_again