"""Fetch an untrusted public article with pinned DNS, verified TLS, and strict resource limits."""
import hashlib
import http.client
import ipaddress
import socket
import multiprocessing
import ssl
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES, MAX_TEXT, DEADLINE, REDIRECTS = 2 * 1024 * 1024, 50000, 20, 3


class FetchError(RuntimeError):
    pass


def resolve(host, port, timeout):
    # The outer fetch process bounds system DNS resolution and slow HTTP headers together.
    return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


def destination(url, timeout=5):
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if port != (443 if parsed.scheme == "https" else 80) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii")
        if "%" in host:
            raise ValueError()
        addresses = resolve(host, port, max(0.01, timeout))
        if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast or ipaddress.ip_address(address).is_reserved for address in addresses):
            raise ValueError()
        return parsed, host, port, addresses[0]
    except (ValueError, UnicodeError, OSError):
        raise FetchError("unsafe_or_unresolvable_url") from None


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden, self.in_title, self.title, self.parts, self.date = [], False, [], [], ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.hidden.append(tag)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and attrs.get("property") == "article:published_time":
            self.date = attrs.get("content", "")[:100]

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden:
            (self.title if self.in_title else self.parts).append(data)


def _fetch(url):
    original, deadline = url, time.monotonic() + DEADLINE
    try:
        for redirect in range(REDIRECTS + 1):
            parsed, host, port, address = destination(url, min(5, max(0.01, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("fetch_timeout")
            # Connect to the validated IP, never re-resolve the hostname during the HTTP request.
            sock = socket.create_connection((address, port), timeout=min(remaining, 5))
            connection = http.client.HTTPConnection(host, port, timeout=min(remaining, 5))
            response = None
            try:
                if parsed.scheme == "https":
                    try:
                        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
                    except BaseException:
                        sock.close()
                        raise
                if time.monotonic() >= deadline:
                    sock.close()
                    raise FetchError("fetch_timeout")
                connection.sock = sock
                path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                authority = f"[{host}]" if ":" in host else host
                sock.settimeout(max(0.01, min(5, deadline - time.monotonic())))
                connection.request("GET", path, headers={"Host": authority, "User-Agent": "AlfaNews/1.0", "Accept": "text/html,text/plain", "Accept-Encoding": "identity", "Connection": "close"})
                sock.settimeout(max(0.01, min(5, deadline - time.monotonic())))
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location or redirect == REDIRECTS:
                        raise FetchError("redirect_limit")
                    next_url = urljoin(url, location)
                    if parsed.scheme == "https" and urlsplit(next_url).scheme != "https":
                        raise FetchError("unsafe_redirect")
                    url = next_url
                    continue
                if response.status != 200:
                    raise FetchError("article_unavailable")
                content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
                if content_type not in ("text/html", "text/plain") or response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise FetchError("unsupported_content")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                    raise FetchError("article_too_large")
                body = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise FetchError("fetch_timeout")
                    sock.settimeout(min(remaining, 5))
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise FetchError("article_too_large")
                charset = response.headers.get_content_charset() or "utf-8"
                decoded = body.decode(charset, errors="replace")
                if content_type == "text/html":
                    parser = Text()
                    parser.feed(decoded)
                    title, text, published = " ".join(parser.title), " ".join(parser.parts), parser.date
                else:
                    title, text, published = "", decoded, ""
                text = " ".join(text.split())[:MAX_TEXT]
                if not text:
                    raise FetchError("empty_article")
                return {"source_id": "user:" + uuid.uuid4().hex, "title": " ".join(title.split())[:200] or host,
                        "link": urlunsplit(parsed._replace(fragment="")), "original_url": original, "summary": text,
                        "published": published, "content_hash": hashlib.sha256(body).hexdigest(), "outlets": [host], "origin": "human"}
            finally:
                if response is not None:
                    response.close()
                connection.close()
                sock.close()
    except FetchError:
        raise
    except (OSError, http.client.HTTPException, LookupError, ValueError):
        raise FetchError("fetch_failed") from None


def _fetch_child(connection, url):
    try:
        connection.send((True, _fetch(url)))
    except FetchError as error:
        connection.send((False, str(error)))
    except Exception:
        connection.send((False, "fetch_failed"))
    finally:
        connection.close()


def fetch(url):
    """A killable process enforces the deadline even for DNS stalls and slow HTTP headers."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_fetch_child, args=(child, url), daemon=True)
    try:
        process.start()
        child.close()
        if not parent.poll(DEADLINE):
            raise FetchError("fetch_timeout")
        ok, payload = parent.recv()
        if not ok:
            raise FetchError(payload)
        return payload
    except (EOFError, OSError):
        raise FetchError("fetch_failed") from None
    finally:
        child.close()
        parent.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
