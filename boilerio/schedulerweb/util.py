from flask import g, current_app

from . import model


def get_db():
    if not hasattr(g, 'db'):
        g.db = model.db_connect(
            current_app.config.get('DB_HOST'),
            current_app.config.get('DB_USER'),
            current_app.config.get('DB_NAME'),
            current_app.config.get('DB_PASSWORD'))
    return g.db
