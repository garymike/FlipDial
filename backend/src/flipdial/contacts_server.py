"""Set up the optional bundled contacts server (Radicale) for people who don't have one.

`flipdial contacts-server init` writes everything Radicale needs into one folder:

    config        Radicale settings: HTTPS, sign-in, access rules, storage
    rights        who can open what (below)
    users         user names with bcrypt password hashes (no passwords)
    ca.pem        a certificate authority made for this server only
    server.pem    the server's certificate, signed by it, for the names given
    server.key    its private key (readable by the owner only)
    collections/  the contacts, as plain .vcf files

Access rules: the "flipdial" account can open everything. Every other account (a phone)
can open only its own address books. Passwords are random and shown once; only their
bcrypt hashes are stored.
"""

from __future__ import annotations

import ipaddress
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

FLIPDIAL_USER = "flipdial"
PORT = 5232
USERNAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
CERT_YEARS = 10

CONFIG = """\
# Written by `flipdial contacts-server init`. See docs/sync.md.
[server]
hosts = 0.0.0.0:{port}
ssl = True
certificate = {dir}/server.pem
key = {dir}/server.key
max_content_length = 10000000

[auth]
type = htpasswd
htpasswd_filename = {dir}/users
htpasswd_encryption = bcrypt
delay = 1

[rights]
type = from_file
file = {dir}/rights

[storage]
filesystem_folder = {dir}/collections

[web]
type = none

[logging]
level = warning
mask_passwords = True
"""

RIGHTS = """\
# Written by `flipdial contacts-server init`. The first matching rule wins.

# FlipDial's own account opens everything: its address book and each phone's.
[flipdial]
user: flipdial
collection: .*
permissions: RrWw

# Anyone signed in can see the top level (needed to find their own address books).
[root]
user: .+
collection:
permissions: R

# Every other account opens only its own address books.
[own-home]
user: .+
collection: {user}
permissions: RW

[own-books]
user: .+
collection: {user}/[^/]+
permissions: rw
"""


class ServerSetupError(ValueError):
    pass


def _password() -> str:
    return secrets.token_urlsafe(18)


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _private(path: Path, data: bytes) -> None:
    """Write a file only its owner can read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _names(hosts: list[str]) -> list[x509.GeneralName]:
    out: list[x509.GeneralName] = []
    for h in dict.fromkeys(["localhost", "127.0.0.1", "contacts", *hosts]):
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            out.append(x509.DNSName(h))
    return out


def _constraints(hosts: list[str]) -> x509.NameConstraints:
    """Limit the authority to this server's names, so even a stolen key couldn't vouch for
    any other website (for devices that check name constraints, which iOS and OpenSSL do)."""
    permitted: list[x509.GeneralName] = []
    for name in _names(hosts):
        if isinstance(name, x509.IPAddress):
            ip = name.value
            permitted.append(x509.IPAddress(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}")))
        else:
            permitted.append(name)
    return x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None)


def make_certificates(folder: Path, hosts: list[str]) -> None:
    """A certificate authority for this server only, and the server's certificate."""
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FlipDial contacts server CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365 * CERT_YEARS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_constraints(hosts), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    # Apple limits certificates for servers to 825 days.
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(_names(hosts)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    (folder / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (folder / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _private(
        folder / "server.key",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    # The CA key is not kept: a new address means new certificates (renew_certificates).


def renew_certificates(folder: Path, hosts: list[str]) -> None:
    """New certificates for new addresses. Accounts and contacts are kept; phones need the
    new certificate (set them up again)."""
    if not (folder / "users").is_file():
        raise ServerSetupError("not_set_up")
    make_certificates(folder, hosts)


def init(folder: Path, hosts: list[str], config_dir: str | None = None) -> dict[str, str]:
    """Write a new contacts server setup. Refuses to overwrite an existing one.

    `config_dir` is where the folder is seen by Radicale (inside its container, say);
    by default the folder itself. Returns FlipDial's password, shown once."""
    if not hosts:
        raise ServerSetupError("host_required")
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "users").exists():
        raise ServerSetupError("already_set_up")
    where = config_dir or str(folder.resolve())
    (folder / "config").write_text(CONFIG.format(port=PORT, dir=where))
    (folder / "rights").write_text(RIGHTS)
    (folder / "collections").mkdir(exist_ok=True)
    password = _password()
    _private(folder / "users", f"{FLIPDIAL_USER}:{_hash(password)}\n".encode())
    make_certificates(folder, hosts)
    return {"username": FLIPDIAL_USER, "password": password}


def settings_lines(folder: Path, login: dict[str, str], inside: str, host: str) -> str:
    """The settings FlipDial needs for this server, as lines for the settings file."""
    return (
        f"FLIPDIAL_RADICALE_DIR={folder}\n"
        f"FLIPDIAL_CARDDAV_URL=https://{inside}:{PORT}/\n"
        f"FLIPDIAL_CARDDAV_USERNAME={login['username']}\n"
        f"FLIPDIAL_CARDDAV_PASSWORD={login['password']}\n"
        f"FLIPDIAL_CARDDAV_CA_BUNDLE={folder / 'ca.pem'}\n"
        f"FLIPDIAL_PHONE_SERVER_URL=https://{host}:{PORT}/\n"
    )


def write_private_note(folder: Path, name: str, text: str) -> Path:
    """Write something secret (a password) to an owner-only file for the person to copy."""
    path = folder / name
    _private(path, text.encode())
    return path


def users(folder: Path) -> list[str]:
    path = folder / "users"
    if not path.is_file():
        return []
    return [line.split(":", 1)[0] for line in path.read_text().splitlines() if ":" in line]


def add_user(folder: Path, username: str) -> str:
    """Add an account (for a phone). Returns its password, shown once."""
    if not USERNAME.match(username) or username == FLIPDIAL_USER:
        raise ServerSetupError("bad_username")
    if not (folder / "users").is_file():
        raise ServerSetupError("not_set_up")
    if username in users(folder):
        raise ServerSetupError("user_exists")
    password = _password()
    with open(folder / "users", "a", encoding="utf-8") as fh:
        fh.write(f"{username}:{_hash(password)}\n")
    return password


def next_phone_name(folder: Path) -> str:
    taken = set(users(folder))
    if "phone" not in taken:
        return "phone"
    n = 2
    while f"phone{n}" in taken:
        n += 1
    return f"phone{n}"
