from __future__ import annotations

import socket
import ssl
from email.message import Message
from io import BytesIO
from pathlib import Path
from time import monotonic
from unittest.mock import MagicMock, patch

import certifi
import pytest

from automd.security import SecurityError, _connect, download_url


def test_transport_dials_the_validated_endpoint_and_keeps_tls_hostname() -> None:
    endpoint = ("1.1.1.1", 443)
    with (
        patch("automd.security.socket.getaddrinfo") as dns,
        patch("automd.security.socket.socket") as socket_factory,
        patch("automd.security.ssl.create_default_context") as context,
    ):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", endpoint)]
        connection = _connect("example.org", 443, https=True, deadline=monotonic() + 2)
        dns.assert_called_once()
        socket_factory.return_value.connect.assert_called_once_with(endpoint)
        context.assert_called_once_with(cafile=certifi.where())
        assert context.return_value.minimum_version == ssl.TLSVersion.TLSv1_2
        context.return_value.wrap_socket.assert_called_once_with(
            socket_factory.return_value, server_hostname="example.org"
        )
        assert connection.host == "example.org"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "224.0.0.1"])
def test_transport_refuses_nonpublic_resolver_results(address: str) -> None:
    with (
        patch("automd.security.socket.getaddrinfo") as dns,
        patch("automd.security.socket.socket") as socket_factory,
    ):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]
        with pytest.raises(SecurityError, match="public"):
            _connect("example.org", 80, https=False, deadline=monotonic() + 2)
        socket_factory.assert_not_called()


def _response(payload: bytes, status: int = 200, **extra: str) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = status
    response.length = None
    response.headers = Message()
    response.headers["Content-Type"] = "text/plain"
    response.getheader.side_effect = lambda name, default=None: extra.get(name, default)
    response.read1.side_effect = BytesIO(payload).read
    return response


def test_download_revalidates_redirects_and_strips_query_from_provenance(tmp_path: Path) -> None:
    with patch("automd.security._connect") as connect:
        connect.return_value.getresponse.side_effect = [
            _response(b"", status=302, Location="https://example.net/result?query=placeholder"),
            _response(b"safe text"),
        ]
        result = download_url("https://example.org/start", tmp_path / "result", max_bytes=32)
    assert [call.args[0] for call in connect.call_args_list] == ["example.org", "example.net"]
    assert connect.return_value.request.call_args.args == ("GET", "/result?query=placeholder")
    assert result.final_url == "https://example.net/result"
    assert result.path.read_bytes() == b"safe text"


def test_download_limit_removes_partial_result(tmp_path: Path) -> None:
    destination = tmp_path / "result"
    with patch("automd.security._connect") as connect:
        connect.return_value.getresponse.return_value = _response(b"x" * 16)
        with pytest.raises(SecurityError, match="size"):
            download_url("https://example.org", destination, max_bytes=8)
    assert not destination.exists()
