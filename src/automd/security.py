from __future__ import annotations

import http.client
import ipaddress
import os
import re
import shutil
import socket
import ssl
import stat
import tarfile
import unicodedata
import urllib.parse
import zipfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import IO, cast

import certifi

from . import __version__
from .config import LIMITS, Limits


class SecurityError(ValueError):
    """Raised when untrusted input violates a safety boundary."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    final_url: str
    content_type: str
    size: int


@dataclass(slots=True)
class ArchiveBudget:
    entries_left: int
    bytes_left: int

    def consume(self, size: int) -> None:
        if self.entries_left <= 0 or not 0 <= size <= self.bytes_left:
            raise SecurityError("Archive exceeds the remaining extraction budget")
        self.entries_left -= 1
        self.bytes_left -= size


_WINDOWS_DEVICE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$", re.IGNORECASE
)
_SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_GITHUB_HOSTS = frozenset({"api.github.com", "codeload.github.com"})
_IPV6_TRANSITION = tuple(
    ipaddress.IPv6Network(value) for value in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16")
)


def _reserved_name(part: str) -> bool:
    return bool(_WINDOWS_DEVICE.fullmatch(part.partition(".")[0].rstrip(" ")))


def validate_source_id(value: str) -> str:
    if not _SOURCE_ID.fullmatch(value) or _reserved_name(value):
        raise SecurityError("Invalid source identifier")
    return value


def safe_filename(value: str, default: str = "automd-output") -> str:
    value = Path(value.replace("\\", "/")).name
    value = re.sub(r"[\x00-\x1f\x7f]+", "", value)
    value = re.sub(r"[^\w. -]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"[ -]+", "-", value).strip("-.")
    value = value[:120].encode("utf-8")[:200].decode("utf-8", errors="ignore").rstrip("-.")
    return ("_" + value if _reserved_name(value) else value) or default


def safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    if len(normalized) > 2_048 or normalized.startswith("/"):
        raise SecurityError("Absolute or oversized file path")
    # TAR producers commonly prefix members with ./ and give directories a trailing slash.
    parts = normalized.split("/")
    while parts and parts[0] == ".":
        parts.pop(0)
    if parts and not parts[-1]:
        parts.pop()
    if not parts or len(parts) > 64:
        raise SecurityError("Empty or overly deep file path")
    for part in parts:
        if part in {"", ".", ".."}:
            raise SecurityError("Invalid path component")
        if (
            len(part.encode("utf-8", errors="surrogatepass")) > 255
            or part.endswith((".", " "))
            or _reserved_name(part)
            or re.search(r'[\x00-\x1f\x7f<>:"|?*\ud800-\udfff]', part)
        ):
            raise SecurityError("File path contains an unsupported or reserved component")
    return PurePosixPath(*parts)


def resolve_inside(root: Path, relative: str | PurePosixPath) -> Path:
    path = safe_relative_path(str(relative))
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*path.parts).resolve()
    if root_resolved not in candidate.parents:
        raise SecurityError("Resolved path leaves the job workspace")
    return candidate


def _parse_http_url(value: str) -> urllib.parse.SplitResult:
    if len(value) > 4_096 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise SecurityError("Invalid URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname or ""
        hostname.encode("idna")
        if not hostname or "%" in hostname or port == 0:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise SecurityError("Invalid URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError("Only HTTP(S) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise SecurityError("Credentials are not accepted in URLs")
    return parsed


def _hostname(parsed: urllib.parse.SplitResult) -> str:
    return (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii")


def _port(parsed: urllib.parse.SplitResult) -> int:
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _public_endpoints(
    hostname: str, port: int
) -> list[tuple[int, tuple[str, int] | tuple[str, int, int, int]]]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SecurityError("Unable to resolve the remote host") from exc
    endpoints: list[tuple[int, tuple[str, int] | tuple[str, int, int, int]]] = []
    for family, _, _, _, sockaddr in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise SecurityError("Unsupported remote address family")
        endpoint = cast(tuple[str, int] | tuple[str, int, int, int], sockaddr)
        address = ipaddress.ip_address(endpoint[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or (
                isinstance(address, ipaddress.IPv6Address)
                and (address.teredo is not None or any(address in net for net in _IPV6_TRANSITION))
            )
        ):
            raise SecurityError("Only public unicast destination addresses are allowed")
        endpoints.append((family, endpoint))
    if not endpoints:
        raise SecurityError("Unable to resolve the remote host")
    return list(dict.fromkeys(endpoints))


def validate_public_url(value: str, *, github_only: bool = False) -> urllib.parse.SplitResult:
    parsed = _parse_http_url(value.strip())
    hostname = _hostname(parsed)
    if github_only and hostname != "github.com":
        raise SecurityError("Only public github.com repositories are supported")
    _public_endpoints(hostname, _port(parsed))
    return parsed


def parse_github_repo(value: str) -> tuple[str, str]:
    parsed = _parse_http_url(value.strip())
    if _hostname(parsed) != "github.com" or parsed.port not in {None, 80, 443}:
        raise SecurityError("Only public github.com repositories are supported")
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise SecurityError("Use a repository root URL such as https://github.com/owner/repo")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    pattern = re.compile(r"[A-Za-z0-9_.-]{1,100}")
    if any(part in {".", ".."} or not pattern.fullmatch(part) for part in (owner, repo)):
        raise SecurityError("Invalid GitHub owner or repository name")
    return owner, repo


def github_archive_url(value: str, ref: str | None) -> str:
    owner, repo = parse_github_repo(value)
    base = f"https://api.github.com/repos/{owner}/{repo}/zipball"
    if ref:
        if ref in {".", ".."} or len(ref) > 200 or any(ord(char) < 32 for char in ref):
            raise SecurityError("Invalid GitHub ref")
        return f"{base}/{urllib.parse.quote(ref, safe='')}"
    return base


def _remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Remote download timed out")
    return min(remaining, 10.0)


def _connect(
    hostname: str, port: int, *, https: bool, deadline: float
) -> http.client.HTTPConnection:
    endpoints = _public_endpoints(hostname, port)
    context = ssl.create_default_context(cafile=certifi.where()) if https else None
    connection = (
        http.client.HTTPSConnection(hostname, port, context=context)
        if context
        else http.client.HTTPConnection(hostname, port)
    )
    last_error: OSError | None = None
    # Connect directly to the vetted socket address. Keep Host and TLS identity on the origin.
    for family, sockaddr in endpoints:
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(_remaining(deadline))
            sock.connect(sockaddr)
            connection.sock = (
                context.wrap_socket(sock, server_hostname=hostname) if context else sock
            )
            return connection
        except ssl.SSLCertVerificationError:
            sock.close()
            raise
        except OSError as exc:
            sock.close()
            last_error = exc
    raise OSError("Unable to connect to the remote host") from last_error


def download_url(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    limits: Limits = LIMITS,
    github: bool = False,
    check_cancelled: Callable[[], None] = lambda: None,
) -> DownloadResult:
    deadline = monotonic() + limits.remote_timeout_seconds
    current = url.strip()
    tls_required = False
    created = False
    complete = False
    try:
        for hop in range(limits.max_redirects + 1):
            check_cancelled()
            parsed = _parse_http_url(current)
            hostname, port = _hostname(parsed), _port(parsed)
            https = parsed.scheme == "https"
            if tls_required and not https:
                raise SecurityError("HTTPS redirects cannot downgrade to HTTP")
            if github and (not https or port != 443 or hostname not in _GITHUB_HOSTS):
                raise SecurityError("Unexpected GitHub archive destination")
            tls_required = tls_required or https
            target = urllib.parse.quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                target += "?" + urllib.parse.quote(parsed.query, safe="/?%:@!$&'()*+,;=-._~")
            with closing(_connect(hostname, port, https=https, deadline=deadline)) as connection:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "application/zip,application/octet-stream"
                        if github
                        else "text/*,application/xhtml+xml,application/xml",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "User-Agent": f"Auto-MD/{__version__} (+https://github.com/tegridydev/auto-md)",
                    },
                )
                with connection.getresponse() as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.getheader("Location")
                        if not location or hop == limits.max_redirects:
                            raise SecurityError("Invalid redirect or too many redirects")
                        current = urllib.parse.urljoin(current, location)
                        continue
                    if response.status != 200:
                        raise ValueError(f"Remote source returned HTTP {response.status}")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise SecurityError("Remote source used an unsupported content encoding")
                    if response.length is not None and not 0 <= response.length <= max_bytes:
                        raise SecurityError("Remote source exceeds the configured size limit")
                    advertised_size = response.length
                    content_type = response.headers.get_content_type()
                    if not github and not (
                        content_type.startswith("text/")
                        or content_type in {"application/xhtml+xml", "application/xml"}
                    ):
                        raise ValueError(f"Unsupported remote content type: {content_type}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    size = 0
                    with destination.open("xb") as output:
                        created = True
                        while True:
                            check_cancelled()
                            _remaining(deadline)
                            chunk = response.read1(min(1024 * 1024, max_bytes - size + 1))
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                raise SecurityError(
                                    "Remote source exceeds the configured size limit"
                                )
                            output.write(chunk)
                    if advertised_size is not None and size != advertised_size:
                        raise ValueError("Remote download ended early")
                    complete = True
                    # Query strings can contain access tokens. Keep them out of result provenance.
                    return DownloadResult(
                        destination,
                        parsed._replace(query="", fragment="").geturl(),
                        content_type,
                        size,
                    )
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("Remote download failed or timed out") from exc
    finally:
        if created and not complete:
            destination.unlink(missing_ok=True)
    raise SecurityError("Too many redirects")


def path_key(path: PurePosixPath) -> str:
    return unicodedata.normalize("NFC", path.as_posix()).casefold()


class _BoundedTarInfo(tarfile.TarInfo):
    # tarfile reads extended metadata before yielding a member to the caller.
    def _proc_pax(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        if not 0 <= self.size <= 64 * 1024:
            raise SecurityError("TAR extended metadata exceeds its size limit")
        return super()._proc_pax(archive)  # type: ignore[misc,no-any-return]

    def _proc_gnulong(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        if not 0 <= self.size <= 64 * 1024:
            raise SecurityError("TAR long name exceeds its size limit")
        return super()._proc_gnulong(archive)  # type: ignore[misc,no-any-return]

    def _proc_sparse(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        raise SecurityError("TAR sparse files are not supported")

    def _proc_gnusparse_10(
        self,
        next_info: tarfile.TarInfo,
        pax_headers: dict[str, str],
        archive: tarfile.TarFile,
    ) -> None:
        raise SecurityError("TAR sparse files are not supported")


def _zip_members(
    handle: zipfile.ZipFile,
    budget: ArchiveBudget,
    max_file_bytes: int,
) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    members = []
    seen: set[str] = set()
    for member in handle.infolist():
        budget.consume(member.file_size)
        if member.file_size > max_file_bytes:
            raise SecurityError("Archive member exceeds the per-file limit")
        if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
            raise SecurityError("Archive links and encrypted files are not supported")
        relative = safe_relative_path(member.orig_filename)
        key = path_key(relative)
        if key in seen:
            raise SecurityError("Archive contains conflicting member paths")
        seen.add(key)
        members.append((member, relative))
    return members


def validate_docx(path: Path) -> None:
    # Office documents are ZIP packages, but their contents are parsed as one document.
    with zipfile.ZipFile(path) as handle:
        members = _zip_members(handle, ArchiveBudget(2_048, 64 * 1024**2), 16 * 1024**2)
        names = {relative.as_posix() for _, relative in members}
        if not {"[Content_Types].xml", "_rels/.rels"} <= names:
            raise SecurityError("Invalid DOCX package")


def extract_archive(
    archive: Path,
    destination: Path,
    *,
    limits: Limits = LIMITS,
    budget: ArchiveBudget | None = None,
    check_cancelled: Callable[[], None] = lambda: None,
) -> None:
    if budget is None:
        budget = ArchiveBudget(limits.max_archive_entries, limits.max_expanded_bytes)
    destination.mkdir(parents=True, exist_ok=False)
    completed = False
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as handle:
                for member, path in _zip_members(handle, budget, limits.max_file_bytes):
                    check_cancelled()
                    target = resolve_inside(destination, path)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    with handle.open(member) as source:
                        _write_member(source, target, member.file_size, check_cancelled)
        else:
            _extract_tar(archive, destination, limits, budget, check_cancelled)
        completed = True
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        raise SecurityError("Unsupported or corrupt archive") from exc
    finally:
        if not completed:
            shutil.rmtree(destination, ignore_errors=True)


def _extract_tar(
    archive: Path,
    destination: Path,
    limits: Limits,
    budget: ArchiveBudget,
    check_cancelled: Callable[[], None],
) -> None:
    seen: set[str] = set()
    with tarfile.open(archive, mode="r:*", tarinfo=_BoundedTarInfo) as handle:
        for member in handle:
            check_cancelled()
            if member.size > limits.max_file_bytes:
                raise SecurityError("Archive member exceeds the per-file limit")
            budget.consume(member.size)
            if member.issparse() or not (member.isdir() or member.isfile()):
                raise SecurityError("TAR links, devices and special files are not supported")
            if member.isdir() and member.name in {".", "./"}:
                continue
            relative = safe_relative_path(member.name)
            key = path_key(relative)
            if key in seen:
                raise SecurityError("Archive contains conflicting member paths")
            seen.add(key)
            target = resolve_inside(destination, relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = handle.extractfile(member)
            if source is None:
                raise SecurityError("Invalid TAR member")
            with source:
                _write_member(source, target, member.size, check_cancelled)


def _write_member(
    source: IO[bytes],
    target: Path,
    expected_size: int,
    check_cancelled: Callable[[], None],
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            check_cancelled()
            size += len(chunk)
            if size > expected_size:
                raise SecurityError("Archive member exceeded its declared size")
            output.write(chunk)
    if size != expected_size:
        raise SecurityError("Archive member ended early")


def ensure_regular_file(path: Path) -> None:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or os.path.islink(path):
        raise SecurityError("Only regular files are supported")
