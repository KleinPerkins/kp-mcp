"""Closed remote URL syntax without endpoint normalization or service access."""
import pytest

from kp_mcp_bootstrap.registrars import RegistrationDefinition, SourceIdentity, StreamableHTTPTransport


@pytest.mark.parametrize("url", [
    "http://example.invalid/mcp", "//example.invalid/mcp", "https:///mcp",
    "https://user@example.invalid/mcp", "https://user:password@example.invalid/mcp",
    "https://example.invalid:bad/mcp", "https://example.invalid:65536/mcp",
    "https://example.invalid:-1/mcp", "https://example.invalid:/mcp",
    "https://example.invalid:１２/mcp", "https://exa mple.invalid/mcp",
    " https://example.invalid/mcp", "https://example.invalid/m cp",
    "https://example.invalid/\tmcp", "https://exa\nmple.invalid/mcp",
    "https://example.invalid/\x00mcp", "https://example.invalid/\x7fmcp",
    "https://example.invalid/mcp?", "https://example.invalid/mcp#",
    "https://example.invalid/mcp?key=value", "https://example.invalid/mcp#fragment",
    "https://example.invalid\\other/mcp", "https://[::1]junk/mcp",
    "https://[not-ipv6]/mcp", "https://[::1]:/mcp",
    "https://example.invalid/%", "https://example.invalid/%2", "https://example.invalid/%zz",
    "https://<example.invalid>/mcp", "https://example.invalid/\ud800",
    None, 123,
])
def test_invalid_remote_url_is_rejected_without_echoing_input(url):
    with pytest.raises(ValueError) as caught:
        StreamableHTTPTransport(url)
    assert str(caught.value) == "streamable HTTP URL must be absolute HTTPS without credentials, query or fragment"


@pytest.mark.parametrize("url", [
    "https://example.invalid", "https://EXAMPLE.invalid:443/mcp/",
    "https://localhost:8443/a//b/../c/%2F%3F%23", "https://[::1]:8443/mcp",
    "https://127.0.0.1/mcp", "https://example.invalid/日本語",
    "https://bücher.invalid/mcp",
])
def test_remote_url_keeps_exact_host_port_path_case_and_escape_bytes(url):
    transport = StreamableHTTPTransport(url)
    identity = SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:url-fixture", "a" * 40, "url-fixture")
    definition = RegistrationDefinition.streamable_http(identity, url=url)
    assert transport.to_record() == {"kind": "streamable-http", "url": url}
    assert definition.transport.url == url
