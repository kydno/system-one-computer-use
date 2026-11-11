import os
from types import SimpleNamespace

import pytest

from typesafe_computer_use import config
from typesafe_computer_use.calls import Calls, MeteredWriter
from typesafe_computer_use.config import custom_writer_endpoint, load_dotenv, writer_base_url
from typesafe_computer_use.writer import WriterError, compose_url, make_writer, parse_json, provider, url_named_in, valid_url


def test_dotenv_sets_only_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CLICKER_TEST_PRESENT", "keep")
    monkeypatch.delenv("CLICKER_TEST_NEW", raising=False)
    (tmp_path / ".env").write_text('# comment\nCLICKER_TEST_PRESENT=override\nCLICKER_TEST_NEW="quoted value"\nbroken line\n')
    load_dotenv(tmp_path / ".env")
    assert os.environ["CLICKER_TEST_PRESENT"] == "keep"
    assert os.environ["CLICKER_TEST_NEW"] == "quoted value"


def test_dotenv_missing_file_is_fine(tmp_path):
    load_dotenv(tmp_path / "nope.env")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://localhost:8081", "http://localhost:8081"),
        ("http://localhost:8081/", "http://localhost:8081"),
        ("http://localhost:8081/v1", "http://localhost:8081"),
        ("http://localhost:8081/v1/messages", "http://localhost:8081"),
        ("https://proxy.example.com/v1/messages/", "https://proxy.example.com"),
    ],
)
def test_the_writer_endpoint_accepts_any_of_its_spellings(given, expected, clean_env):
    clean_env.setenv("CLICKER_WRITER_BASE_URL", given)
    assert writer_base_url() == expected


def test_the_anthropic_base_url_is_left_to_the_sdk(clean_env):
    clean_env.setenv("ANTHROPIC_BASE_URL", "http://localhost:8081")
    assert writer_base_url() is None


def test_an_endpoint_of_its_own_needs_no_key(clean_env, endpoint):
    clean_env.setenv("CLICKER_WRITER_BASE_URL", f"{endpoint.url}/v1/messages")
    assert compose_url(make_writer(), "open example", []) == "https://example.com"
    (request,) = endpoint.seen
    assert request["path"] == "/v1/messages"
    assert request["headers"]["x-api-key"] == "not-needed"


def test_the_endpoint_key_goes_to_the_endpoint_and_no_anthropic_credential_does(clean_env, endpoint):
    clean_env.setenv("CLICKER_WRITER_BASE_URL", endpoint.url)
    clean_env.setenv("CLICKER_WRITER_API_KEY", "proxy-key")
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    clean_env.setenv("ANTHROPIC_AUTH_TOKEN", "oauth-real")
    compose_url(make_writer(), "open example", [])
    headers = endpoint.seen[0]["headers"]
    assert headers["x-api-key"] == "proxy-key"
    assert headers["authorization"] == "Bearer proxy-key"
    assert not any("sk-ant-real" in v or "oauth-real" in v for v in headers.values())


def test_a_bearer_token_still_goes_out_as_a_bearer_token(clean_env, endpoint):
    clean_env.setenv("ANTHROPIC_BASE_URL", endpoint.url)
    clean_env.setenv("ANTHROPIC_AUTH_TOKEN", "oauth-real")
    compose_url(make_writer(), "open example", [])
    headers = endpoint.seen[0]["headers"]
    assert headers["authorization"] == "Bearer oauth-real"
    assert "x-api-key" not in headers


def test_without_credentials_or_an_endpoint_there_is_no_writer(clean_env):
    assert make_writer() is None


def test_a_custom_endpoint_is_told_the_schema_in_the_prompt(clean_env, endpoint):
    clean_env.setenv("CLICKER_WRITER_BASE_URL", endpoint.url)
    endpoint.state["reply"] = 'Here you go:\n```json\n{"ok": true, "url": "https://example.com", "reason": "x"}\n```'
    # Metered, as the runner hands it out.
    assert compose_url(MeteredWriter(make_writer(), Calls()), "open example", []) == "https://example.com"
    assert '"required": ["ok", "url", "reason"]' in endpoint.seen[0]["body"]["system"]
    # Thinking on by default would spend the whole 200-token budget and leave no text.
    assert endpoint.seen[0]["body"]["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    ("env", "custom"),
    [
        ({}, False),
        ({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, False),
        ({"ANTHROPIC_BASE_URL": "http://localhost:1234"}, True),
        ({"CLICKER_WRITER_BASE_URL": "http://localhost:1234/v1/messages"}, True),
    ],
)
def test_the_endpoint_is_custom_whichever_variable_names_it(clean_env, env, custom):
    for name, value in env.items():
        clean_env.setenv(name, value)
    assert custom_writer_endpoint() is custom


def test_anthropic_itself_gets_the_schema_only_through_output_config(clean_env, monkeypatch):
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    writer = make_writer()
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": false, "url": "", "reason": ""}')])

    monkeypatch.setattr(writer.messages, "create", create)
    compose_url(writer, "open example", [])
    assert "schema" not in sent["system"]
    assert "thinking" not in sent
    assert sent["output_config"]["format"]["schema"]["required"] == ["ok", "url", "reason"]


def test_the_startup_line_leaves_credentials_out_of_the_url(clean_env):
    clean_env.setenv("CLICKER_WRITER_BASE_URL", "https://user:secret@proxy.example.com/v1/messages")
    line = provider(make_writer())
    assert line.startswith("https://proxy.example.com (anthropic API)  models:")
    assert "secret" not in line


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"fill": true}', {"fill": True}),
        ('```json\n{"fill": false}\n```', {"fill": False}),
        ('Sure thing:\n{"fill": true, "text": "hi"}\nHope that helps.', {"fill": True, "text": "hi"}),
    ],
)
def test_the_writer_reply_is_read_whether_or_not_it_came_plain(reply, expected):
    assert parse_json(reply) == expected


def test_a_reply_without_any_json_says_so():
    with pytest.raises(WriterError, match="without usable JSON"):
        parse_json("I am not able to help with that.")


def test_valid_url():
    assert valid_url("https://www.cnn.com")
    assert valid_url("https://news.ycombinator.com/newest")
    assert not valid_url("http://www.cnn.com")
    assert not valid_url("https://localhost")
    assert not valid_url("https://www.cnn.com/a b")
    assert not valid_url("")


def test_the_browser_is_the_setting_then_the_system_default_then_chrome(monkeypatch):
    """Asked from Discord to open OpenRouter, a run went to Chrome while Brave was the Mac's browser."""
    monkeypatch.delenv("CLICKER_BROWSER", raising=False)
    assert config.browser() == "Google Chrome"
    assert config.browser("Brave Browser") == "Brave Browser"
    monkeypatch.setenv("CLICKER_BROWSER", "Arc")
    assert config.browser("Brave Browser") == "Arc"


def test_url_named_in_reads_the_one_https_url_a_focus_names():
    assert url_named_in("Open https://docs.example.com/create/new in the address bar.") == "https://docs.example.com/create/new"
    assert url_named_in("Open \u201chttps://example.com/a?b=1\u201d, then wait.") == "https://example.com/a?b=1"
    assert url_named_in("Go to (https://example.com/x).") == "https://example.com/x"
    assert url_named_in("Open https://example.com/x and then https://example.com/x again") == "https://example.com/x"


@pytest.mark.parametrize(
    ("focus", "url"),
    [
        ("Open [https://x.example.com](https://x.example.com).", "https://x.example.com"),  # markdown link, once as text
        ("Open **https://x.example.com/create**", "https://x.example.com/create"),  # emphasis is not part of it
        ("Open _https://x.example.com/create_ now", "https://x.example.com/create"),  # and so is italic
        ("Open https://en.example.org/wiki/Foo_(bar).", "https://en.example.org/wiki/Foo_(bar)"),  # its own parenthesis stays
        ("Go to (https://example.com/x).", "https://example.com/x"),  # one that is not its own goes
        ("Navigate to ~~https://x.example.com/new~~, please", "https://x.example.com/new"),
    ],
)
def test_url_named_in_survives_the_markdown_a_focus_is_written_in(focus, url):
    assert url_named_in(focus) == url


def test_url_named_in_gives_nothing_when_the_text_names_none_or_more_than_one_or_an_unsafe_one():
    assert url_named_in(None) == "" and url_named_in("") == ""
    assert url_named_in("Click the Address and search bar") == ""
    assert url_named_in("Compare https://a.example.com/ with https://b.example.com/") == ""
    assert url_named_in("Open http://example.com/insecure") == ""
    assert url_named_in("Open javascript:alert(1) or file:///etc/passwd") == ""
    assert url_named_in("Open https://localhost/") == ""


@pytest.mark.parametrize(
    "focus",
    [
        "Open https://192.168.1.1/admin",  # an address on the user's own network
        "Open https://[::1]/ in the address bar",  # an IPv6 literal, which urlparse once raised on
        "Open https://router.local/setup",
        "Open https://printer.home.arpa/",
        "Open https://intranet.corp/payroll",
    ],
)
def test_url_named_in_refuses_an_address_on_the_users_own_machine_or_network(focus):
    assert url_named_in(focus) == ""


@pytest.mark.parametrize(
    "focus",
    [
        "The page https://docs.example.com/new is not found; click Blank instead.",  # a page to leave, not to open
        "See [https://x.example.com](https://x.example.com) for the background.",  # mentioned, not asked for
        "Open the menu. The old page https://docs.example.com/new returned a 404.",  # a different sentence's verb
    ],
)
def test_url_named_in_does_not_take_a_url_that_is_only_mentioned(focus):
    assert url_named_in(focus) == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://[bad",
        "https://x.example.com/ with space",
        "https://nodot",
        "ftp://x.example.com/",
        "https://127.0.0.1/",
        "https://[::1]/a.b",
    ],
)
def test_valid_url_says_no_to_text_it_cannot_parse_instead_of_raising(url):
    assert valid_url(url) is False
