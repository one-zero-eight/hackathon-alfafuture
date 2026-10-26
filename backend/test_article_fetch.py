"""Untrusted-URL boundaries use fake sockets and HTTP responses, never external sites."""
import io
import ssl
from email.message import Message

import pytest

from backend import article_fetch as fetcher


class Socket:
    def __init__(self): self.closed = False
    def settimeout(self, timeout): assert 0 < timeout <= 5
    def close(self): self.closed = True


class Response:
    def __init__(self, body=b"<title>Headline</title><script>secret script</script><p>Article text</p>", status=200, **headers):
        self.status, self.body = status, io.BytesIO(body)
        self.headers = Message()
        self.headers["Content-Type"] = headers.pop("Content-Type", "text/html; charset=utf-8")
        for key, value in headers.items(): self.headers[key] = value
    def close(self): self.body.close()
    def getheader(self, name, default=None): return self.headers.get(name, default)
    def read1(self, count): return self.body.read(count)


@pytest.fixture
def network(monkeypatch):
    responses, connections, requests, tls = [], [], [], []
    monkeypatch.setattr(fetcher, "resolve", lambda host, port, timeout: ["93.184.216.34"] if host.endswith("example.org") else [host])
    def connect(address, timeout):
        connections.append(address)
        return Socket()
    class Connection:
        sock = None
        def __init__(self, *args, **kwargs): pass
        def request(self, method, path, headers): requests.append((method, path, headers))
        def getresponse(self): return responses.pop(0)
        def close(self):
            if self.sock: self.sock.close()
    class TLS:
        def wrap_socket(self, sock, server_hostname):
            tls.append(server_hostname)
            return sock
    monkeypatch.setattr(fetcher.socket, "create_connection", connect)
    monkeypatch.setattr(fetcher.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(fetcher.ssl, "create_default_context", TLS)
    return responses, connections, requests, tls


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:password@example.org/", "http://127.0.0.1/", "http://10.0.0.1/", "http://224.0.0.1/", "http://169.254.169.254/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://example.org:8080/", "https://example.org/\nheader"])
def test_private_and_unsupported_destinations_are_rejected(network, url):
    with pytest.raises(fetcher.FetchError): fetcher._fetch(url)
    assert not network[1]


def test_public_address_is_pinned_and_tls_checks_original_hostname(network):
    network[0].append(Response())
    article = fetcher._fetch("https://example.org/article#section")
    assert network[1] == [("93.184.216.34", 443)] and network[3] == ["example.org"]
    assert network[2][0][2]["Host"] == "example.org"
    assert article["summary"] == "Article text" and article["title"] == "Headline"
    assert article["link"] == "https://example.org/article"
    assert article["source_id"].startswith("user:") and "aid" not in article


def test_redirect_is_resolved_again_and_private_or_downgrade_is_rejected(network):
    network[0].append(Response(status=302, Location="http://127.0.0.1/secret"))
    with pytest.raises(fetcher.FetchError): fetcher._fetch("http://example.org/")
    assert len(network[1]) == 1
    network[0].append(Response(status=302, Location="http://example.org/insecure"))
    with pytest.raises(fetcher.FetchError, match="unsafe_redirect"): fetcher._fetch("https://example.org/")


@pytest.mark.parametrize("headers", [{"Content-Type": "application/pdf"}, {"Content-Encoding": "gzip"}, {"Content-Length": str(fetcher.MAX_BYTES + 1)}])
def test_unsupported_and_oversized_responses_fail_without_extraction(network, headers):
    network[0].append(Response(**headers))
    with pytest.raises(fetcher.FetchError): fetcher._fetch("https://example.org/")


def test_streamed_size_limit_and_tls_failure(network, monkeypatch):
    monkeypatch.setattr(fetcher, "MAX_BYTES", 32)
    network[0].append(Response(body=b"x" * 33))
    with pytest.raises(fetcher.FetchError, match="article_too_large"): fetcher._fetch("https://example.org/")
    class BadTLS:
        def wrap_socket(self, *args, **kwargs): raise ssl.SSLCertVerificationError("bad certificate")
    monkeypatch.setattr(fetcher.ssl, "create_default_context", BadTLS)
    with pytest.raises(fetcher.FetchError, match="fetch_failed"): fetcher._fetch("https://example.org/")



def test_outer_deadline_bounds_dns_and_headers(monkeypatch):
    calls = []
    class Pipe:
        def poll(self, timeout): calls.append(timeout); return False
        def close(self): pass
    class Process:
        pid = 1
        def start(self): pass
        def is_alive(self): return True
        def terminate(self): calls.append("terminate")
        def kill(self): calls.append("kill")
        def join(self, timeout): pass
    class Context:
        def Pipe(self, **kwargs): return Pipe(), Pipe()
        def Process(self, **kwargs): return Process()
    monkeypatch.setattr(fetcher.multiprocessing, "get_context", lambda kind: Context())
    with pytest.raises(fetcher.FetchError, match="fetch_timeout"):
        fetcher.fetch("https://example.org/")
    assert calls == [fetcher.DEADLINE, "terminate", "kill"]


def test_real_fetch_process_rejects_loopback_before_connecting():
    with pytest.raises(fetcher.FetchError, match="unsafe_or_unresolvable_url"):
        fetcher.fetch("http://127.0.0.1/")
