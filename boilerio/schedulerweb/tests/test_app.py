import pytest
from http import HTTPStatus
from unittest.mock import patch

from .. import app
from .. import auth

TEST_CLIENT_ID = 'test_client_id'

FAKE_NAME = "Test User"
FAKE_EMAIL = "test@test_account.com"
FAKE_ACCESS_TOKEN = 'wibble_accesstoken'
FAKE_ID_TOKEN = "wibble_idtoken"
FAKE_CLIENT_SECRET = 'wibble_client_secret'
FAKE_USER_ID = "1"
FAKE_PICTURE = "https://lh3.googleusercontent.com/image"
FAKE_SUB = "1"
FAKE_ID_INFO = {
    "iss": "accounts.google.com",
    "azp": TEST_CLIENT_ID,
    "aud": TEST_CLIENT_ID,
    "sub": FAKE_SUB,
    "email": FAKE_EMAIL,
    "email_verified": True,
    "at_hash": "F1LILczsjg7ZXaDv1nqibQ",
    "name": FAKE_NAME,
    "picture": FAKE_PICTURE,
    "given_name": "Test",
    "family_name": "User",
    "locale": "en-GB",
    "iat": 1585415747,
    "exp": 1585419347,
    "jti": "2f2670e487a3e81dae9ccc9e6126f833d3308b61"
}

FAKE_USER_EXPECTED_RESPONSE = {
    'name': FAKE_NAME,
    'picture': FAKE_PICTURE,
}


@pytest.fixture
def client():
    flaskapp = app.create_app({
        'GOOGLE_CLIENT_ID': TEST_CLIENT_ID,
        'SECRET_KEY': 'not_the_real_one',
    })
    yield flaskapp.test_client()


def test_cannot_login_with_no_id_token(client):
    rv = client.post('/me')
    assert rv.status_code == 403


class FakeUserManager(object):
    """A fake user manager that knows about the fake user."""
    def lookup_and_update_google_user(self, google_subscriber_id, name, email,
                                      profile_pic):
        if google_subscriber_id == FAKE_SUB:
            return auth.User(FAKE_USER_ID, name, email)

    def lookup_user(self, user_id):
        if user_id == FAKE_USER_ID:
            return auth.User(FAKE_USER_ID, FAKE_NAME, FAKE_PICTURE)

def test_google_validation_affects_auth_decision(client):
    def never_accept_token(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN
        raise ValueError

    def always_accept_token(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN
        return FAKE_ID_INFO

    app.user_manager = FakeUserManager()
    with patch(__name__ + '.app.google_token.id_token.verify_oauth2_token',
               never_accept_token):
        rv = client.post('/me', data={'id_token': FAKE_ID_TOKEN}, headers={'X-Requested-With': 'test'})
        assert rv.status_code == HTTPStatus.FORBIDDEN

    with patch(__name__ + '.app.google_token.id_token.verify_oauth2_token',
               always_accept_token):
        rv = client.post('/me', data={'id_token': FAKE_ID_TOKEN}, headers={'X-Requested-With': 'test'})
        assert rv.status_code == HTTPStatus.OK


def test_login_and_logout_with_idtoken(client):
    def always_accept_token(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN
        return FAKE_ID_INFO

    app.user_manager = FakeUserManager()
    with patch(__name__ + '.app.google_token.id_token.verify_oauth2_token',
               always_accept_token):

        # Check that, before anyone logged in, there's no user info:
        rv = client.get('/me')
        assert rv.status_code == HTTPStatus.NOT_FOUND

        # Log in with a "valid" token:
        rv = client.post('/me', data={'id_token': FAKE_ID_TOKEN}, headers={'X-Requested-With': 'test'})
        assert rv.status_code == HTTPStatus.OK

        # Retrieve user info and check it's what we expect
        rv = client.get('/me')
        assert rv.json == FAKE_USER_EXPECTED_RESPONSE
        assert rv.status_code == HTTPStatus.OK

        # Log out
        rv = client.delete('/me')
        assert rv.status_code == HTTPStatus.NO_CONTENT or rv.status_code == HTTPStatus.OK

        # Check user info no longer available
        rv = client.get('/me')
        assert rv.status_code == HTTPStatus.NOT_FOUND
        assert FAKE_NAME.encode() not in rv.data


@patch(__name__ + '.app.model.client_secret_is_valid')
@patch(__name__ + '.app.get_db')
@patch(__name__ + '.app.google_token.get_idinfo_from_access_token')
def test_login_with_bad_access_token_rejected(idinfo_from_accesstoken, get_db, client_secret_is_valid, client):
    # Given
    idinfo_from_accesstoken.side_effect = ValueError
    get_db.return_value = None
    client_secret_is_valid.return_value = True

    # When
    rv = client.post('/me', data={
            'access_token': FAKE_ACCESS_TOKEN,
            'client_secret': FAKE_CLIENT_SECRET
        }, headers={'X-Requested-With': 'test'})

    # Then
    assert rv.status_code == HTTPStatus.FORBIDDEN
    idinfo_from_accesstoken.assert_called()
    client_secret_is_valid.assert_called()


@patch(__name__ + '.app.model.client_secret_is_valid')
@patch(__name__ + '.app.get_db')
@patch(__name__ + '.app.google_token.get_idinfo_from_access_token')
def test_login_with_bad_client_secret_and_good_access_token_is_rejected(
        idinfo_from_accesstoken, get_db, client_secret_is_valid, client):
    # Given
    idinfo_from_accesstoken.return_value = FAKE_ID_INFO
    get_db.return_value = None
    client_secret_is_valid.return_value = False

    # When
    rv = client.post('/me', data={
            'access_token': FAKE_ACCESS_TOKEN,
            'client_secret': FAKE_CLIENT_SECRET
        }, headers={'X-Requested-With': 'test'})

    # Then
    assert rv.status_code == HTTPStatus.FORBIDDEN
    client_secret_is_valid.assert_called()
    idinfo_from_accesstoken.assert_not_called()


def test_incomplete_id_token_fails_login(client):
    def always_accept_token(idt, request, client_id):
        assert idt == FAKE_ID_TOKEN
        fake_id_info = FAKE_ID_INFO.copy()
        del fake_id_info['name']
        return fake_id_info

    with patch(__name__ + '.app.google_token.id_token.verify_oauth2_token',
               always_accept_token):
        # Log in with a "valid" token:
        rv = client.post('/me', data={'id_token': FAKE_ID_TOKEN})
        assert rv.status_code == HTTPStatus.FORBIDDEN
