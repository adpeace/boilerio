import pytest
from unittest.mock import patch
from .. import google_token

TEST_CLIENT_ID = 'test_client_id'
FAKE_ID_TOKEN = "wibble"


def test_valueerror_passed_through():
    """Check that auth failures detected by Google's library get propagated."""
    def never_accept_token(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN, "should be called with correct token"
        raise ValueError
    with patch(__name__ + '.google_token.id_token.verify_oauth2_token',
               never_accept_token):
        with pytest.raises(ValueError):
            google_token.validate_id_token(FAKE_ID_TOKEN, TEST_CLIENT_ID)


def test_other_issuer_not_accepted():
    """ID tokens issued by other identity providers aren't acceptable."""
    id_info_with_other_issuer = {'iss': 'not_google'}

    def return_other_issuer(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN, "should be called with correct token"
        return id_info_with_other_issuer
    with patch(__name__ + '.google_token.id_token.verify_oauth2_token',
               return_other_issuer):
        with pytest.raises(ValueError):
            google_token.validate_id_token(FAKE_ID_TOKEN, TEST_CLIENT_ID)


def test_valid_auth_returns_id_info():
    """Good ID token and correct issuer allow authentication."""
    correct_result = {'iss': 'accounts.google.com'}

    def return_google_issuer(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN, "should be called with correct token"
        return correct_result
    with patch(__name__ + '.google_token.id_token.verify_oauth2_token',
               return_google_issuer):
        r = google_token.validate_id_token(FAKE_ID_TOKEN, TEST_CLIENT_ID)
        assert r == correct_result
