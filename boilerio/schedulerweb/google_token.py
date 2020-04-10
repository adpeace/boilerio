from requests.sessions import Session
from cachecontrol import CacheControl
import google.auth.transport.requests
from google.oauth2 import id_token


VALID_ISSUERS = ['accounts.google.com', 'https://accounts.google.com']
CACHED_SESSION = CacheControl(Session())

# XXX Don't hardcode
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def get_idinfo_from_access_token(access_token: str) -> dict:
    """Fetches user information using the access token provided.

    Raises ValueError if an error occurs, including the user not being
    authorized.
    """
    session = Session()
    r = session.get(USERINFO_ENDPOINT, headers={
        'Authorization': 'Bearer ' + access_token
    })
    if r.status_code != 200:
        raise ValueError("Unexpected response code %d" % r.status_code)
    return r.json()


def validate_id_token(idt: str, client_id: str) -> dict:
    """Validate the id_token passed using Google's validation code.

    idt is an id_token, which can be extracted from an OpenID Connect
    authorization response as the 'id_token' field.

    Raises ValueError if the validation failures, otherwise returns the decoded
    token.
    """
    request = google.auth.transport.requests.Request(session=CACHED_SESSION)
    id_info = id_token.verify_oauth2_token(idt, request, client_id)
    if id_info['iss'] not in VALID_ISSUERS:
        raise ValueError('Wrong issuer.')
    return id_info
