import pytest

from .. import config


def write(tmp_path, text):
    path = tmp_path / 'config.ini'
    path.write_text(text)
    return path


def test_default_path():
    assert config.CONFIG_PATH == '/etc/boilerio/config.ini'


def test_loads_current_option_names(tmp_path):
    cfg = config.load_config(write(tmp_path, """
[heating]
backend_url = https://heating.example.com/api
api_key_id = 3
api_key_secret = s3cret
"""))
    assert cfg.get('heating', 'backend_url') == 'https://heating.example.com/api'
    assert config.api_key_credentials(cfg) == ('3', 's3cret')


@pytest.mark.parametrize('old,new', [
    ('scheduler_url', 'backend_url'),
    ('scheduler_username', 'api_key_id'),
    ('scheduler_password', 'api_key_secret'),
])
def test_renamed_options_are_rejected_with_the_new_name(tmp_path, old, new):
    with pytest.raises(ValueError, match=rf"\[heating\] {old} is now {new}"):
        config.load_config(write(tmp_path, f"[heating]\n{old} = x\n"))


def test_api_key_credentials_need_both_values(tmp_path):
    only_id = config.load_config(write(tmp_path, "[heating]\napi_key_id = 3\n"))
    assert config.api_key_credentials(only_id) is None
    no_heating = config.load_config(write(tmp_path, "[mqtt]\nhost = broker\n"))
    assert config.api_key_credentials(no_heating) is None
