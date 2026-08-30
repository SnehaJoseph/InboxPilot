from unittest.mock import patch

from inboxpilot.config import load_settings
from inboxpilot.agent import InboxPilotAgent


def test_agent_can_be_constructed():
    settings = load_settings(env_file=".env.example")
    with patch("inboxpilot.agent.ModelFactory.create", return_value=object()):
        agent = InboxPilotAgent(settings)
    assert agent is not None
