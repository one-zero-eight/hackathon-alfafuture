"""Safe fetch of a user's link: address checks, pinning, redirects, limits, content types. The network is replaced by fakes."""
import pytest

from backend import article_fetch as af

HTML = ("<html><head><title>Ставка выросла</title></head><body><nav>меню</nav><p>" + "Центральный банк повысил ключевую ставку, это влияет на кредиты. " * 3
        + "</p><script>x()</script></body></html>").encode()


def serve(monkeypatch, pages, ip="93.184.216.34"):
    """pages: url -> (status, headers, body). Returns the list of (ip, host, path) requested."""
    seen = []
    monkeypatch.setattr(af, "resolve", lambda host, port: ip)

    def request(parts, port, address, started):
        seen.append((address, parts.hostname, parts.path))
        return pages[f"{parts.scheme}://{parts.hostname}{parts.path}"]

    monkeypatch.setattr(af, "request", request)
    return seen


def test_article_text_and_title_are_extracted_and_the_address_is_pinned(monkeypatch):
    seen = serve(monkeypatch, {"https://news.example/a": (200, {"content-type": "text/html; charset=utf-8"}, HTML)})
    got = af.fetch("https://news.example/a")
    assert got["title"] == "Ставка выросла" and "Центральный банк" in got["summary"] and "меню" not in got["summary"] and "x()" not in got["summary"]
    assert got["ref"].startswith("user:") and got["origin"] == "human" and got["outlets"] == ["news.example"]
    assert seen == [("93.184.216.34", "news.example", "/a")]


@pytest.mark.parametrize("url", ["ftp://example.com/a", "file:///etc/passwd", "https://user:pw@example.com/", "https://example.com:8443/a", "http:///x", "javascript:alert(1)"])
def test_unsupported_schemes_credentials_and_ports_are_rejected(url):
    with pytest.raises(af.FetchError, match="unsafe_or_unresolvable_url"):
        af.fetch(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1", "fd00::1", "0.0.0.0"])
def test_non_public_addresses_are_rejected(monkeypatch, address):
    monkeypatch.setattr(af.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(af.FetchError, match="unsafe_or_unresolvable_url"):
        af.resolve("evil.example", 443)


def test_one_private_answer_among_public_ones_rejects_the_host(monkeypatch):
    monkeypatch.setattr(af.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(af.FetchError):
        af.resolve("mixed.example", 443)


def test_every_redirect_hop_is_checked_and_their_number_is_limited(monkeypatch):
    def resolve(host, port):
        if host == "internal.example":
            raise af.FetchError("unsafe_or_unresolvable_url")
        return "93.184.216.34"

    monkeypatch.setattr(af, "resolve", resolve)
    pages = {"https://a.example/x": (302, {"location": "https://internal.example/secret"}, b""),
             "https://loop.example/1": (302, {"location": "/2"}, b""), "https://loop.example/2": (302, {"location": "/3"}, b""),
             "https://loop.example/3": (302, {"location": "/4"}, b""), "https://loop.example/4": (302, {"location": "/5"}, b"")}
    monkeypatch.setattr(af, "request", lambda parts, port, ip, started: pages[f"{parts.scheme}://{parts.hostname}{parts.path}"])
    with pytest.raises(af.FetchError, match="unsafe_or_unresolvable_url"):
        af.fetch("https://a.example/x")
    with pytest.raises(af.FetchError, match="fetch_failed"):
        af.fetch("https://loop.example/1")


def test_redirect_to_a_relative_path_is_followed(monkeypatch):
    serve(monkeypatch, {"https://news.example/old": (301, {"location": "/new"}, b""),
                        "https://news.example/new": (200, {"content-type": "text/html"}, HTML)})
    got = af.fetch("https://news.example/old")
    assert got["link"] == "https://news.example/new" and got["original_url"] == "https://news.example/old"


@pytest.mark.parametrize("content_type, body", [("application/pdf", b"%PDF-1.4"), ("image/png", b"\x89PNG"), ("text/html", "<html><body>коротко</body></html>".encode())])
def test_unsupported_or_empty_content_is_rejected(monkeypatch, content_type, body):
    serve(monkeypatch, {"https://news.example/a": (200, {"content-type": content_type}, body)})
    with pytest.raises(af.FetchError, match="unsupported_content"):
        af.fetch("https://news.example/a")


def test_plain_text_is_accepted(monkeypatch):
    serve(monkeypatch, {"https://news.example/story.txt": (200, {"content-type": "text/plain"}, ("Текст новости. " * 20).encode())})
    assert af.fetch("https://news.example/story.txt")["title"] == "story.txt"


def test_real_request_enforces_the_size_limit_and_does_not_leave_the_pinned_address(monkeypatch):
    """The real request() against a local transport: oversized bodies stop the read, the connection goes to the pinned address."""
    import httpx

    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.host, request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * (af.MAX_BYTES + 10))

    real = httpx.Client
    monkeypatch.setattr(af.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    parts, port = af.checked("https://news.example/a")
    with pytest.raises(af.FetchError, match="article_too_large"):
        af.request(parts, port, "93.184.216.34", af.time.monotonic())
    assert calls == [("93.184.216.34", "news.example", "news.example")]
