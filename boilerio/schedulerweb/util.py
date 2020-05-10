from flask import g, current_app, request
from http import HTTPStatus

from . import model


def get_db():
    if not hasattr(g, 'db'):
        g.db = model.db_connect(
            current_app.config.get('DB_HOST'),
            current_app.config.get('DB_USER'),
            current_app.config.get('DB_NAME'),
            current_app.config.get('DB_PASSWORD'))
    return g.db


# Decorator to add CSRF protection to any mutating function.
#
# Adding this header to the client forces the browser to first do an OPTIONS
# call, determine that the origin is not allowed, and block the subsequent
# call. (Ordinarily, the call is made but the result not made available to
# the client if the origin is not allowed, but the damage is already done.)
# Checking for the presence of this header on the server side prevents
# clients from bypassing this check.
#
# Add this decorator to all mutating operations.
def csrf_protection(fn):
    """Require that the X-Requested-With header is present."""
    def protected(*args, **kwargs):
        if 'X-Requested-With' in request.headers:
            return fn(*args, **kwargs)
        else:
            return "X-Requested-With header missing", HTTPStatus.FORBIDDEN
    return protected
