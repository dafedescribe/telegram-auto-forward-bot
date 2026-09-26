import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forwarder import chunk_messages, has_email, parse_source_chats, validate_config


class FakeMsg:
    def __init__(self, text=None, message=None):
        self.text = text
        self.message = message


def test_has_email_detects_plain_address():
    assert has_email(FakeMsg(text="contact me at foo@example.com thanks")) is True


def test_has_email_rejects_no_address():
    assert has_email(FakeMsg(text="hello world, no contact")) is False
    assert has_email(FakeMsg(text=None, message=None)) is False


def test_parse_source_chats_parses_ids():
    assert parse_source_chats("-100123, -100456") == {-100123, -100456}


def test_parse_source_chats_rejects_garbage():
    try:
        parse_source_chats("not-a-chat")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for garbage chat id")


def test_validate_config_requires_secrets():
    env = {}
    try:
        validate_config(env)
    except RuntimeError as e:
        assert "API_ID" in str(e) or "SOURCE_CHATS" in str(e) or "required" in str(e).lower()
    else:
        raise AssertionError("expected RuntimeError for empty env")


def test_validate_config_accepts_good_env():
    env = {
        "API_ID": "12345",
        "API_HASH": "abcdef123456",
        "SESSION_STRING": "dummy",
        "SOURCE_CHATS": "-100123,-100456",
        "DESTINATION_URL": "https://example.com/webhook",
    }
    cfg = validate_config(env)
    assert cfg["api_id"] == 12345
    assert cfg["source_chats"] == {-100123, -100456}


def test_chunk_messages_splits():
    assert chunk_messages([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
