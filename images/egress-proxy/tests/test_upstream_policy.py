import pytest
from proxy.policy import UpstreamPolicy


def test_disabled_when_no_upstream_configured():
    assert UpstreamPolicy.from_env({}) is None


def test_fallback_direct_defaults_off():
    up = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80"})
    assert up.fallback_direct is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", " True "])
def test_fallback_direct_enabled_by_truthy_values(val):
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_FALLBACK_DIRECT": val,
    })
    assert up.fallback_direct is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_fallback_direct_disabled_by_falsy_values(val):
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_FALLBACK_DIRECT": val,
    })
    assert up.fallback_direct is False


def test_parses_upstream_with_credentials():
    up = UpstreamPolicy.from_env(
        {"EGRESS_UPSTREAM_PROXY": "http://user-rotate:secret@p.webshare.io:80"}
    )
    assert up.host == "p.webshare.io"
    assert up.port == 80
    assert up.username == "user-rotate"
    assert up.password == "secret"


def test_parses_upstream_without_credentials():
    up = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://proxy.internal:3128"})
    assert (up.host, up.port) == ("proxy.internal", 3128)
    assert up.username is None and up.password is None


def test_defaults_to_port_80_when_omitted():
    up = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://proxy.internal"})
    assert up.port == 80


def test_credentials_are_percent_decoded():
    # Webshare passwords can contain reserved chars; they must be encoded in the URL.
    up = UpstreamPolicy.from_env(
        {"EGRESS_UPSTREAM_PROXY": "http://user:p%40ss%3Aword@p.webshare.io:80"}
    )
    assert up.username == "user"
    assert up.password == "p@ss:word"


def test_proxy_authorization_header_is_basic_encoded():
    up = UpstreamPolicy.from_env(
        {"EGRESS_UPSTREAM_PROXY": "http://user-rotate:secret@p.webshare.io:80"}
    )
    # base64("user-rotate:secret")
    assert up.proxy_authorization() == "Basic dXNlci1yb3RhdGU6c2VjcmV0"


def test_no_proxy_authorization_header_without_credentials():
    up = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://proxy.internal:3128"})
    assert up.proxy_authorization() is None


# ---- routing modes --------------------------------------------------------

def test_routes_everything_upstream_when_no_lists_given():
    up = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80"})
    assert up.route("example.com") is True
    assert up.route("api.anthropic.com") is True


def test_exclude_mode_bypasses_listed_hosts_and_chains_the_rest():
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_EXCLUDE": "api.anthropic.com, api.openai.com",
    })
    assert up.route("api.anthropic.com") is False
    assert up.route("api.openai.com") is False
    assert up.route("linkedin.com") is True


def test_include_mode_chains_only_listed_hosts():
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_INCLUDE": "linkedin.com,glassdoor.com",
    })
    assert up.route("linkedin.com") is True
    assert up.route("glassdoor.com") is True
    assert up.route("api.anthropic.com") is False


def test_setting_both_lists_is_a_config_error():
    with pytest.raises(ValueError, match="EGRESS_UPSTREAM_EXCLUDE.*EGRESS_UPSTREAM_INCLUDE"):
        UpstreamPolicy.from_env({
            "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
            "EGRESS_UPSTREAM_EXCLUDE": "api.anthropic.com",
            "EGRESS_UPSTREAM_INCLUDE": "linkedin.com",
        })


def test_list_without_upstream_is_a_config_error():
    with pytest.raises(ValueError, match="EGRESS_UPSTREAM_PROXY"):
        UpstreamPolicy.from_env({"EGRESS_UPSTREAM_EXCLUDE": "api.anthropic.com"})


def test_malformed_upstream_url_is_a_config_error():
    with pytest.raises(ValueError, match="EGRESS_UPSTREAM_PROXY"):
        UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "p.webshare.io:80"})  # no scheme


# ---- suffix matching ------------------------------------------------------

def test_list_matches_subdomains():
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_EXCLUDE": "example.com",
    })
    assert up.route("example.com") is False
    assert up.route("api.example.com") is False
    assert up.route("a.b.example.com") is False


def test_list_does_not_match_on_a_non_label_boundary():
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_EXCLUDE": "example.com",
    })
    # "notexample.com" merely ends with the same characters — it must still chain.
    assert up.route("notexample.com") is True


def test_list_matching_is_case_insensitive():
    up = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_EXCLUDE": "Example.COM",
    })
    assert up.route("API.Example.com") is False


def test_mode_reports_the_configured_list_kind():
    none_ = UpstreamPolicy.from_env({"EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80"})
    excl = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_EXCLUDE": "a.example",
    })
    incl = UpstreamPolicy.from_env({
        "EGRESS_UPSTREAM_PROXY": "http://p.webshare.io:80",
        "EGRESS_UPSTREAM_INCLUDE": "a.example",
    })
    assert none_.mode == "all"
    assert excl.mode == "exclude"
    assert incl.mode == "include"
