import configparser

CONFIG_PATH = '/etc/boilerio/config.ini'

# Options renamed in 0.5.0, as (section, old name): new name. Configuration
# files using the old names are rejected with a message naming the new ones,
# rather than failing later with a less helpful missing-option error.
RENAMED_OPTIONS = {
    ('heating', 'scheduler_url'): 'backend_url',
    ('heating', 'scheduler_username'): 'api_key_id',
    ('heating', 'scheduler_password'): 'api_key_secret',
}


def load_config(path=CONFIG_PATH):
    cfg = configparser.RawConfigParser()
    with open(path, 'r') as f:
        cfg.read_file(f)
    check_renamed_options(cfg)
    return cfg


def check_renamed_options(cfg):
    renamed = [f"[{section}] {old} is now {new}"
               for (section, old), new in RENAMED_OPTIONS.items()
               if cfg.has_option(section, old)]
    if renamed:
        raise ValueError("Configuration uses renamed options: " + "; ".join(renamed))


def api_key_credentials(cfg):
    """Return the (API key ID, secret) pair for the server, or None if the
    configuration doesn't set both."""
    if cfg.has_option('heating', 'api_key_id') and \
       cfg.has_option('heating', 'api_key_secret'):
        return cfg.get('heating', 'api_key_id'), cfg.get('heating', 'api_key_secret')
    return None
