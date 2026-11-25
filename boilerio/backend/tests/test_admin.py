import hmac
from unittest.mock import MagicMock

import pytest

from .. import admin, auth, model


def make_db(fetchone):
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone
    db = MagicMock()
    db.cursor.return_value = cursor
    return db, cursor


def test_add_api_key_credentials_authenticate():
    db, cursor = make_db((7,))
    api_key_id, secret = admin.add_api_key(db)
    assert api_key_id == 7
    db.commit.assert_called_once()

    # Read the stored row back as the server's API key login does.
    hashed, salt = cursor.execute.call_args.args[1]
    cursor.rowcount = 1
    cursor.fetchone.return_value = (7, hashed, salt)
    api_key = model.ApiKey.get_by_id(db, 7)
    assert hmac.compare_digest(
        auth.hash_password(secret, api_key.salt).decode(), api_key.secret_hashed)
    assert not hmac.compare_digest(
        auth.hash_password(secret + 'x', api_key.salt).decode(), api_key.secret_hashed)


def test_add_api_key_generates_distinct_secrets():
    db, _ = make_db((1,))
    assert admin.add_api_key(db)[1] != admin.add_api_key(db)[1]


def test_add_user(monkeypatch):
    monkeypatch.setattr(model.UserIdentity, 'lookup_user_by_google_id',
                        classmethod(lambda cls, db, gid: None))
    db, cursor = make_db((3,))
    assert admin.add_user(db, '1234', 'Andy', 'a@example.com') == 3
    assert cursor.execute.call_args.args[1] == ('1234', 'Andy', 'a@example.com')
    db.commit.assert_called_once()


def test_add_user_rejects_duplicate(monkeypatch):
    monkeypatch.setattr(model.UserIdentity, 'lookup_user_by_google_id',
                        classmethod(lambda cls, db, gid: object()))
    db, cursor = make_db(None)
    with pytest.raises(ValueError):
        admin.add_user(db, '1234', '', '')
    cursor.execute.assert_not_called()
    db.commit.assert_not_called()


def test_main_add_api_key_prints_key_and_config(monkeypatch, tmp_path, capsys):
    settings = tmp_path / 'settings.cfg'
    settings.write_text("DB_HOST='h'\nDB_NAME='n'\nDB_USER='u'\nDB_PASSWORD='p'\n")
    monkeypatch.setenv('BOILERIO_SETTINGS', str(settings))
    db, _ = make_db((5,))
    connected = []
    monkeypatch.setattr(model, 'db_connect',
                        lambda *a: connected.append(a) or db)
    admin.main(['add-api-key'])
    assert connected == [('h', 'n', 'u', 'p')]
    out = capsys.readouterr().out
    assert 'API key ID:     5' in out
    assert 'api_key_id = 5' in out
    assert 'api_key_secret = ' in out
    db.close.assert_called_once()
