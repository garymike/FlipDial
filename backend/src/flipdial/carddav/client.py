"""A small CardDAV client (RFC 6352) built on httpx.

Safety choices:
- XML is parsed with defusedxml and size-capped
- redirects are followed only within the same scheme and host, at most 3 times
- every href the server returns must stay inside the chosen address book
- TLS is verified; a custom CA bundle can be set for servers with their own certificate
- credentials never appear in errors or logs
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

import httpx
from defusedxml import ElementTree as ET

from flipdial.carddav.vcard import VCard, VCardError, valid_uid
from flipdial.config import Settings

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3


class CardDAVError(Exception):
    """Log-safe error. `code` never includes URLs, user names or contact data."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code if status is None else f"{code} (HTTP {status})")
        self.code, self.status = code, status


class ConflictError(CardDAVError):
    """The contact changed on the server since it was read (ETag mismatch)."""


@dataclass
class Remote:
    href: str
    etag: str | None


@dataclass
class AddressBook:
    url: str
    name: str


def escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _propfind(props: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">'
        f"<d:prop>{props}</d:prop></d:propfind>"
    ).encode()


class CardDAVClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        book: str | None = None,
    ):
        """`book` picks another address book on the same server (the phone book)."""
        if not settings.carddav_url:
            raise CardDAVError("carddav_not_configured")
        auth = None
        if settings.carddav_username and settings.carddav_password:
            auth = httpx.BasicAuth(
                settings.carddav_username, settings.carddav_password.get_secret_value()
            )
        verify: bool | ssl.SSLContext = settings.carddav_verify_tls
        if settings.carddav_ca_bundle:
            verify = ssl.create_default_context(cafile=str(settings.carddav_ca_bundle))
        self.start = settings.carddav_url
        self.wanted = book or settings.carddav_addressbook
        # On FlipDial's own contacts server, its address book is made on first use.
        self.make_missing = not book and bool(settings.radicale_dir)
        # The phone book is never picked as the main address book by default.
        from flipdial.phone_rules import book_name

        self.avoid = None if book else (book_name(settings) or None)
        if not book and self.avoid and self.wanted == self.avoid:
            raise CardDAVError("phone_book_is_main_book")
        self.version = settings.vcard_version
        self.http = httpx.Client(
            auth=auth,
            verify=verify,
            timeout=30.0,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "FlipDial"},
        )
        self._book: AddressBook | None = None

    # -- HTTP plumbing --------------------------------------------------------------

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        origin = urlparse(url)
        for _ in range(MAX_REDIRECTS + 1):
            try:
                r = self.http.request(method, url, **kw)
            except httpx.HTTPError as exc:
                raise CardDAVError("server_unreachable") from exc
            if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                nxt = urljoin(url, r.headers["location"])
                p = urlparse(nxt)
                if (p.scheme, p.netloc) != (origin.scheme, origin.netloc):
                    raise CardDAVError("redirect_off_host")
                url = nxt
                continue
            if r.status_code == 401:
                raise CardDAVError("auth_failed", 401)
            return r
        raise CardDAVError("too_many_redirects")

    def _xml(self, r: httpx.Response):
        if len(r.content) > MAX_XML_BYTES:
            raise CardDAVError("response_too_large")
        try:
            return ET.fromstring(r.content)
        except Exception as exc:  # defusedxml raises several types
            raise CardDAVError("bad_xml") from exc

    def _propfind_xml(self, url: str, props: str, depth: str):
        r = self._request(
            "PROPFIND",
            url,
            content=_propfind(props),
            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
        )
        if r.status_code != 207:
            raise CardDAVError("propfind_failed", r.status_code)
        return self._xml(r)

    # -- discovery ------------------------------------------------------------------

    def address_book(self) -> AddressBook:
        if self._book:
            return self._book
        if self.wanted and (self.wanted.startswith("/") or "://" in self.wanted):
            # An address given by its path: open it directly (another account's book).
            url = urljoin(self.start, self.wanted)
            if urlparse(url).netloc != urlparse(self.start).netloc:
                raise CardDAVError("address_book_not_found")
            found = self._books_at(url if url.endswith("/") else url + "/", "0")
            if not found:
                raise CardDAVError("address_book_not_found")
            self._book = found[0]
            return self._book
        books = self._find_books()
        if not books and self.make_missing and not self.wanted:
            books = [self.create_book("Contacts")]
        if not books:
            raise CardDAVError("no_address_book")

        def named(b: AddressBook, name: str) -> bool:
            return name in (b.name, urlparse(b.url).path, b.url)

        if self.wanted:
            books = [b for b in books if named(b, self.wanted)]
            if not books:
                raise CardDAVError("address_book_not_found")
        elif self.avoid:
            books = [b for b in books if not named(b, self.avoid)]
            if not books:
                raise CardDAVError("no_address_book")
        self._book = books[0]
        return self._book

    def books(self) -> list[AddressBook]:
        """Every address book this account can see."""
        try:
            home = self._home()
        except CardDAVError:
            return self._find_books()
        return self._books_at(home, "1")

    def create_book(self, name: str, url: str | None = None) -> AddressBook:
        """Make a new address book next to the others, or at `url` (RFC 5689 extended
        MKCOL)."""
        slug = "".join(ch for ch in name.lower() if ch.isalnum()) or "phone"
        url = urljoin(self.start, url) if url else urljoin(self._home(), slug + "/")
        if urlparse(url).netloc != urlparse(self.start).netloc:
            raise CardDAVError("cannot_create_book")
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:mkcol xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:set><d:prop>'
            "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>"
            f"<d:displayname>{escape_xml(name)}</d:displayname>"
            "</d:prop></d:set></d:mkcol>"
        ).encode()
        r = self._request(
            "MKCOL", url, content=body, headers={"Content-Type": "application/xml; charset=utf-8"}
        )
        if r.status_code == 405:
            raise CardDAVError("book_exists", 405)
        if r.status_code not in (200, 201):
            raise CardDAVError("cannot_create_book", r.status_code)
        return AddressBook(url, name)

    def _home(self) -> str:
        root = self._propfind_xml(self.start, "<d:current-user-principal/>", "0")
        href = root.findtext(".//d:current-user-principal/d:href", namespaces=NS)
        principal = urljoin(self.start, href) if href else self.start
        root = self._propfind_xml(principal, "<c:addressbook-home-set/>", "0")
        home = root.findtext(".//c:addressbook-home-set/d:href", namespaces=NS)
        if not home:
            raise CardDAVError("no_address_book_home")
        return urljoin(principal, home)

    def _find_books(self) -> list[AddressBook]:
        here = self._books_at(self.start, "0")
        if here:
            return here
        root = self._propfind_xml(self.start, "<d:current-user-principal/>", "0")
        href = root.findtext(".//d:current-user-principal/d:href", namespaces=NS)
        principal = urljoin(self.start, href) if href else self.start
        root = self._propfind_xml(principal, "<c:addressbook-home-set/>", "0")
        home = root.findtext(".//c:addressbook-home-set/d:href", namespaces=NS)
        if not home:
            raise CardDAVError("no_address_book_home")
        return self._books_at(urljoin(principal, home), "1")

    def _books_at(self, url: str, depth: str) -> list[AddressBook]:
        root = self._propfind_xml(url, "<d:resourcetype/><d:displayname/>", depth)
        books = []
        for resp in root.findall("d:response", NS):
            if resp.find(".//d:resourcetype/c:addressbook", NS) is None:
                continue
            href = resp.findtext("d:href", namespaces=NS) or ""
            name = resp.findtext(".//d:displayname", namespaces=NS) or ""
            book_url = urljoin(url, href)
            if not book_url.endswith("/"):
                book_url += "/"
            books.append(AddressBook(book_url, name))
        return books

    # -- contacts -------------------------------------------------------------------

    def _inside_book(self, href: str) -> str:
        book = self.address_book().url
        url = urljoin(book, href)
        b, u = urlparse(book), urlparse(url)
        if (
            (b.scheme, b.netloc) != (u.scheme, u.netloc)
            or not unquote(u.path).startswith(unquote(b.path))
            or ".." in unquote(u.path)
        ):
            raise CardDAVError("href_outside_address_book")
        return url

    def list(self) -> list[Remote]:
        root = self._propfind_xml(
            self.address_book().url, "<d:getetag/><d:getcontenttype/><d:resourcetype/>", "1"
        )
        out = []
        for resp in root.findall("d:response", NS):
            if resp.find(".//d:resourcetype/d:collection", NS) is not None:
                continue
            href = resp.findtext("d:href", namespaces=NS)
            if not href:
                continue
            etag = resp.findtext(".//d:getetag", namespaces=NS)
            out.append(Remote(self._inside_book(href), etag))
        return out

    def get(self, href: str) -> tuple[VCard, str | None]:
        r = self._request("GET", self._inside_book(href))
        if r.status_code == 404:
            raise CardDAVError("not_found", 404)
        if r.status_code != 200:
            raise CardDAVError("get_failed", r.status_code)
        try:
            return VCard.parse(r.text), r.headers.get("etag")
        except VCardError as exc:
            raise CardDAVError(str(exc)) from exc

    def href_for(self, uid: str) -> str:
        if not valid_uid(uid):
            raise CardDAVError("bad_uid")
        return self.address_book().url + uid + ".vcf"

    def create(self, card: VCard) -> Remote:
        href = self.href_for(card.uid)
        r = self._put(href, card, {"If-None-Match": "*"})
        if r.status_code == 412:
            raise ConflictError("already_exists", 412)
        return Remote(href, r.headers.get("etag") or self._etag(href))

    def update(self, href: str, card: VCard, etag: str | None) -> Remote:
        href = self._inside_book(href)
        r = self._put(href, card, {"If-Match": etag} if etag else {})
        if r.status_code == 412:
            raise ConflictError("changed_on_server", 412)
        return Remote(href, r.headers.get("etag") or self._etag(href))

    def delete(self, href: str, etag: str | None) -> None:
        href = self._inside_book(href)
        r = self._request("DELETE", href, headers={"If-Match": etag} if etag else {})
        if r.status_code == 412:
            raise ConflictError("changed_on_server", 412)
        if r.status_code not in (200, 204, 404):
            raise CardDAVError("delete_failed", r.status_code)

    def _put(self, href: str, card: VCard, headers: dict[str, str]) -> httpx.Response:
        r = self._request(
            "PUT",
            href,
            content=card.render().encode(),
            headers={"Content-Type": "text/vcard; charset=utf-8", **headers},
        )
        if r.status_code not in (200, 201, 204, 412):
            raise CardDAVError("put_failed", r.status_code)
        return r

    def _etag(self, href: str) -> str | None:
        root = self._propfind_xml(href, "<d:getetag/>", "0")
        return root.findtext(".//d:getetag", namespaces=NS)

    def close(self) -> None:
        self.http.close()
