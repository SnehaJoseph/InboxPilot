from inboxpilot.config import load_settings


def test_load_settings_defaults():
    settings = load_settings(env_file=".env.example")
    assert settings.app_name == "InboxPilot"
    assert settings.log_level == "INFO"
