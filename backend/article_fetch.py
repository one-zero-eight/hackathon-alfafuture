"""Safe download of a news article by a user's link (docs/backend.md): public HTTP(S) hosts only, the resolved address is checked and
pinned for the connection (the TLS name stays the host), redirects are re-checked hop by hop, time and size are bounded, HTML/text only.
Nothing is written to the collector tables; the article lives in the profile's feedback state."""

import hashlib
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES, MAX_REDIRECTS, DEADLINE, TEXT_LIMIT = 1_500_000, 3, 15.0, 20000
PORTS = {"http": (80,), "https": (443,)}


class FetchError(RuntimeError):
    """args[0] is a stable code the orchestrator maps to a user message."""


def resolve(host: str, port: int) -> str:
    """One public address of the host; any non-public answer rejects the URL (DNS rebinding to private ranges)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    except (OSError, ValueError):
        raise FetchError("unsafe_or_unresolvable_url") from None
    if not addresses or not all(a.is_global for a in addresses):
        raise FetchError("unsafe_or_unresolvable_url")
    return str(addresses[0])


def checked(url: str):
    parts = urlsplit(url)
    if (
        parts.scheme not in PORTS
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise FetchError("unsafe_or_unresolvable_url")
    try:
        port = parts.port or PORTS[parts.scheme][0]
    except ValueError:
        raise FetchError("unsafe_or_unresolvable_url") from None
    if port not in PORTS[parts.scheme]:
        raise FetchError("unsafe_or_unresolvable_url")
    return parts, port


def request(parts, port: int, ip: str, started: float) -> tuple[int, dict, bytes]:
    """One GET to the pinned address. Returns (status, headers, body); the body is cut at the size limit."""
    target = (
        f"{parts.scheme}://{f'[{ip}]' if ':' in ip else ip}:{port}{parts.path or '/'}"
        + (f"?{parts.query}" if parts.query else "")
    )
    headers = {
        "Host": parts.hostname,
        "Accept": "text/html,text/plain;q=0.9",
        "Accept-Encoding": "identity",
        "User-Agent": "alfa-news-analytics/1.0",
    }
    body = b""
    try:
        with httpx.Client(
            timeout=httpx.Timeout(DEADLINE, connect=5.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream(
                "GET",
                target,
                headers=headers,
                extensions={"sni_hostname": parts.hostname},
            ) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    return r.status_code, dict(r.headers), b""
                if r.status_code != 200:
                    raise FetchError("fetch_failed")
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FetchError("article_too_large")
                    if time.monotonic() - started > DEADLINE:
                        raise FetchError("fetch_timeout")
                return r.status_code, dict(r.headers), body
    except httpx.TimeoutException:
        raise FetchError("fetch_timeout") from None
    except httpx.HTTPError:
        raise FetchError("fetch_failed") from None


class Reader(HTMLParser):
    SKIP = {
        "script",
        "style",
        "noscript",
        "svg",
        "template",
        "head",
        "nav",
        "footer",
        "form",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.title, self.og, self.chunks, self.in_title = (
            0,
            "",
            "",
            [],
            False,
        )

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag == "meta" and dict(attrs).get("property") == "og:title":
            self.og = (dict(attrs).get("content") or "").strip()
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.depth and data.strip():
            self.chunks.append(data.strip())


def parse(body: bytes, content_type: str, url: str) -> tuple[str, str]:
    kind = content_type.split(";")[0].strip().lower()
    if kind not in ("text/html", "text/plain"):
        raise FetchError("unsupported_content")
    found = re.search(
        rb"charset=[\"']?([\w-]+)", content_type.encode() + b" " + body[:2048], re.I
    )
    try:
        text = body.decode(found.group(1).decode() if found else "utf-8", "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")
    if kind == "text/plain":
        title, content = (
            urlsplit(url).path.rsplit("/", 1)[-1] or urlsplit(url).hostname,
            text,
        )
    else:
        reader = Reader()
        reader.feed(text)
        title, content = (
            (reader.og or " ".join(reader.title.split())),
            "\n".join(
                c for c in reader.chunks if len(c) > 40 or len(reader.chunks) < 5
            ),
        )
    content = content.strip()[:TEXT_LIMIT]
    if len(content) < 80:
        raise FetchError("unsupported_content")
    return (title or urlsplit(url).hostname)[:300], content


def fetch(url: str) -> dict:
    """The article as a source of the profile: {ref, title, link, summary, outlets, date, origin}."""
    started, current = time.monotonic(), url
    for _ in range(MAX_REDIRECTS + 1):
        parts, port = checked(current)
        status, headers, body = request(
            parts, port, resolve(parts.hostname, port), started
        )
        if status == 200:
            title, content = parse(body, headers.get("content-type", ""), current)
            return {
                "ref": "user:" + hashlib.sha1(current.encode()).hexdigest()[:16],
                "title": title,
                "link": current,
                "original_url": url,
                "summary": content,
                "outlets": [parts.hostname],
                "date": "",
                "origin": "human",
            }
        location = headers.get("location")
        if not location:
            raise FetchError("fetch_failed")
        current = urljoin(current, location)
    raise FetchError("fetch_failed")
