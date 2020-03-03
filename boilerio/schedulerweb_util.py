from flask import g

from .config import load_config
from . import model


def get_conf():
    if not hasattr(g, 'conf'):
        g.conf = load_config()
    return g.conf


def get_db():
    conf = get_conf()
    if not hasattr(g, 'db'):
        g.db = model.db_connect(
            conf.get('heating', 'scheduler_db_host'),
            conf.get('heating', 'scheduler_db_name'),
            conf.get('heating', 'scheduler_db_user'),
            conf.get('heating', 'scheduler_db_password'))
    return g.db
