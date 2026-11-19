"""Private registrar state and durable target I/O."""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .contracts import RegistrationContext, bounded_id, digest_bytes


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _inside_git(path: Path) -> bool:
    current = path
    while True:
        marker = current / ".git"
        if marker.exists() or marker.is_symlink():
            return True
        if current == current.parent:
            return False
        current = current.parent


def _assert_no_symlink_components(path: Path, *, allow_leaf: bool) -> None:
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, component in enumerate(parts):
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
        if stat.S_ISLNK(info.st_mode) and not (allow_leaf and index == len(parts) - 1):
            raise RegistrarError(ReasonCode.TARGET_CHANGED)


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _darwin_libc() -> ctypes.CDLL:
    library = ctypes.util.find_library("c")
    if library is None:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    return ctypes.CDLL(library, use_errno=True)


def _read_xattrs(path: Path) -> tuple[tuple[str, bytes], ...]:
    """Read all extended attributes or refuse when capability is unavailable."""

    if hasattr(os, "listxattr") and hasattr(os, "getxattr"):
        try:
            return tuple(
                sorted(
                    (name, os.getxattr(path, name))
                    for name in os.listxattr(path)
                )
            )
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    if sys.platform != "darwin":
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    libc = _darwin_libc()
    listxattr = libc.listxattr
    listxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    listxattr.restype = ctypes.c_ssize_t
    getxattr = libc.getxattr
    getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    getxattr.restype = ctypes.c_ssize_t
    encoded_path = os.fsencode(path)
    size = listxattr(encoded_path, None, 0, 0)
    if size < 0:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    if size == 0:
        return ()
    names_buffer = ctypes.create_string_buffer(size)
    observed = listxattr(encoded_path, names_buffer, size, 0)
    if observed != size:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    names = tuple(filter(None, names_buffer.raw[:size].split(b"\0")))
    values: list[tuple[str, bytes]] = []
    for encoded_name in names:
        value_size = getxattr(encoded_path, encoded_name, None, 0, 0, 0)
        if value_size < 0:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED)
        value_buffer = ctypes.create_string_buffer(max(value_size, 1))
        observed_size = getxattr(
            encoded_path,
            encoded_name,
            value_buffer,
            value_size,
            0,
            0,
        )
        if observed_size != value_size:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED)
        values.append((os.fsdecode(encoded_name), value_buffer.raw[:value_size]))
    return tuple(sorted(values))


def _write_xattr(path: Path, name: str, value: bytes) -> None:
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(path, name, value)
            return
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    if sys.platform != "darwin":
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    libc = _darwin_libc()
    setxattr = libc.setxattr
    setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    setxattr.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(value, max(len(value), 1))
    if setxattr(
        os.fsencode(path),
        os.fsencode(name),
        buffer,
        len(value),
        0,
        0,
    ) != 0:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)


def _has_extended_acl(path: Path, xattrs: tuple[tuple[str, bytes], ...]) -> bool:
    if any(name.startswith("system.posix_acl_") for name, _value in xattrs):
        return True
    if sys.platform != "darwin":
        return False
    libc = _darwin_libc()
    acl_get_file = libc.acl_get_file
    acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    acl_get_file.restype = ctypes.c_void_p
    acl_free = libc.acl_free
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int
    acl = acl_get_file(os.fsencode(path), 0x00000100)
    if not acl:
        if ctypes.get_errno() == errno.ENOENT:
            return False
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    try:
        return True
    finally:
        acl_free(acl)


@dataclass(frozen=True, slots=True)
class TargetBinding:
    logical_path: Path
    resolved_path: Path
    target_id: str
    existed: bool
    leaf_symlink: bool
    link_text: str | None
    target_identity: tuple[int, int] | None
    parent_identities: tuple[tuple[str, int, int], ...]
    resolved_parent_identities: tuple[tuple[str, int, int], ...]
    mode: int | None
    uid: int | None
    gid: int | None
    flags: int
    xattrs: tuple[tuple[str, bytes], ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "logical_path": str(self.logical_path),
            "resolved_path": str(self.resolved_path),
            "target_id": self.target_id,
            "existed": self.existed,
            "leaf_symlink": self.leaf_symlink,
            "link_text": self.link_text,
            "target_identity": list(self.target_identity) if self.target_identity else None,
            "parent_identities": [list(item) for item in self.parent_identities],
            "resolved_parent_identities": [
                list(item) for item in self.resolved_parent_identities
            ],
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "flags": self.flags,
            "xattrs": [
                {"name": name, "digest": digest_bytes(value)}
                for name, value in self.xattrs
            ],
        }


def _parent_identities(path: Path) -> tuple[tuple[str, int, int], ...]:
    parent_identities: list[tuple[str, int, int]] = []
    current = Path(path.anchor)
    for component in path.parent.parts[1:]:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            raise RegistrarError(ReasonCode.TARGET_CHANGED)
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
        if not stat.S_ISDIR(info.st_mode):
            raise RegistrarError(ReasonCode.TARGET_CHANGED)
        parent_identities.append((str(current), info.st_dev, info.st_ino))
    return tuple(parent_identities)


def inspect_target(path: Path) -> TargetBinding:
    logical = path.absolute()
    if not logical.is_absolute():
        raise RegistrarError(ReasonCode.TARGET_CHANGED)
    _assert_no_symlink_components(logical, allow_leaf=True)
    parent_identities = _parent_identities(logical)
    try:
        leaf_info = logical.lstat()
    except FileNotFoundError:
        return TargetBinding(
            logical_path=logical,
            resolved_path=logical,
            target_id=bounded_id(str(logical)),
            existed=False,
            leaf_symlink=False,
            link_text=None,
            target_identity=None,
            parent_identities=parent_identities,
            resolved_parent_identities=parent_identities,
            mode=None,
            uid=None,
            gid=None,
            flags=0,
            xattrs=(),
        )
    except OSError:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    leaf_symlink = stat.S_ISLNK(leaf_info.st_mode)
    link_text: str | None = None
    resolved = logical
    if leaf_symlink:
        try:
            link_text = os.readlink(logical)
        except OSError:
            raise RegistrarError(ReasonCode.TARGET_CHANGED) from None
        try:
            resolved = logical.resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            raise RegistrarError(ReasonCode.TARGET_CHANGED) from None
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
        _assert_no_symlink_components(resolved, allow_leaf=False)
    resolved_parent_identities = _parent_identities(resolved)
    try:
        info = resolved.stat()
    except OSError:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RegistrarError(ReasonCode.TARGET_CHANGED)
    if info.st_uid != os.getuid():
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    flags = getattr(info, "st_flags", 0)
    if flags:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    xattrs = _read_xattrs(resolved)
    if _has_extended_acl(resolved, xattrs):
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    return TargetBinding(
        logical_path=logical,
        resolved_path=resolved,
        target_id=bounded_id(str(resolved)),
        existed=True,
        leaf_symlink=leaf_symlink,
        link_text=link_text,
        target_identity=_file_identity(info),
        parent_identities=parent_identities,
        resolved_parent_identities=resolved_parent_identities,
        mode=stat.S_IMODE(info.st_mode),
        uid=info.st_uid,
        gid=info.st_gid,
        flags=flags,
        xattrs=xattrs,
    )


def recheck_target(binding: TargetBinding) -> None:
    current = inspect_target(binding.logical_path)
    if (
        current.resolved_path != binding.resolved_path
        or current.existed != binding.existed
        or current.leaf_symlink != binding.leaf_symlink
        or current.link_text != binding.link_text
        or current.target_identity != binding.target_identity
        or current.parent_identities != binding.parent_identities
        or current.resolved_parent_identities != binding.resolved_parent_identities
        or current.mode != binding.mode
        or current.uid != binding.uid
        or current.gid != binding.gid
        or current.flags != binding.flags
        or current.xattrs != binding.xattrs
    ):
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=binding.target_id)


def read_target(binding: TargetBinding) -> bytes | None:
    recheck_target(binding)
    if not binding.existed:
        return None
    try:
        return binding.resolved_path.read_bytes()
    except OSError:
        raise RegistrarError(
            ReasonCode.PERMISSION_DENIED, target_id=binding.target_id
        ) from None


def atomic_replace_target(binding: TargetBinding, data: bytes | None) -> None:
    recheck_target(binding)
    target = binding.resolved_path
    if data is None:
        if binding.existed:
            target.unlink()
            _fsync_directory(target.parent)
        return
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".kp-mcp.tmp"
    )
    temporary = Path(temporary_name)
    try:
        mode = binding.mode if binding.mode is not None else 0o600
        os.fchmod(descriptor, mode)
        if binding.uid is not None and binding.gid is not None:
            os.fchown(descriptor, binding.uid, binding.gid)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for name, value in binding.xattrs:
            _write_xattr(temporary, name, value)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    if binding.leaf_symlink and not binding.logical_path.is_symlink():
        raise RegistrarError(ReasonCode.VERIFICATION_FAILED, target_id=binding.target_id)
    observed = inspect_target(binding.logical_path)
    if (
        observed.mode != mode
        or observed.uid != (binding.uid if binding.uid is not None else os.getuid())
        or (binding.gid is not None and observed.gid != binding.gid)
        or observed.flags != binding.flags
        or (binding.existed and observed.xattrs != binding.xattrs)
    ):
        raise RegistrarError(ReasonCode.VERIFICATION_FAILED, target_id=binding.target_id)


class StateStore:
    """Validated mode-0700 state root containing only mode-0600 regular files."""

    def __init__(self, context: RegistrationContext) -> None:
        self.context = context
        self.root = context.state_directory.absolute()
        self._validate_root()

    def _validate_root(self) -> None:
        _assert_no_symlink_components(self.root, allow_leaf=False)
        try:
            info = self.root.lstat()
        except FileNotFoundError:
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            ) from None
        except OSError:
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            ) from None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or _inside_git(self.root)
        ):
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            )

    def prepared_path(self, record_id: str) -> Path:
        return self.root / f"prepared-{record_id}.json"

    def receipt_path(self, target_id: str | None = None) -> Path:
        key = bounded_id(
            "|".join(
                (
                    target_id or self.context.target_id,
                    self.context.host,
                    self.context.scope,
                    self.context.connection_id,
                )
            )
        )
        return self.root / f"receipt-{key}.json"

    def journal_path(self, operation_id: str) -> Path:
        return self.root / f"journal-{operation_id}.json"

    def terminal_path(self, operation_id: str) -> Path:
        return self.root / f"terminal-{operation_id}.json"

    def lock_path(self, target_id: str | None = None) -> Path:
        return self.root / f"lock-{target_id or self.context.target_id}.lck"

    def read_optional(self, path: Path) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError:
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            ) from None
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=self.context.target_id
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        finally:
            os.close(descriptor)

    def write(self, path: Path, data: bytes) -> bool:
        existing = self.read_optional(path)
        if existing == data:
            return False
        if existing is not None:
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.root), prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(self.root)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        return True

    def replace(self, path: Path, data: bytes) -> None:
        existing = self.read_optional(path)
        if existing == data:
            return
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.root), prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(self.root)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def remove(self, path: Path) -> None:
        existing = self.read_optional(path)
        if existing is None:
            return
        path.unlink()
        _fsync_directory(self.root)

    @contextmanager
    def lock(self, target_id: str | None = None) -> Iterator[None]:
        path = self.lock_path(target_id)
        common_flags = os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        common_flags |= getattr(os, "O_NOFOLLOW", 0)
        created = False
        try:
            descriptor = os.open(path, common_flags)
        except FileNotFoundError:
            try:
                descriptor = os.open(
                    path,
                    common_flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                created = True
            except FileExistsError:
                try:
                    descriptor = os.open(path, common_flags)
                except OSError:
                    raise RegistrarError(
                        ReasonCode.STATE_INVALID,
                        target_id=self.context.target_id,
                    ) from None
            except OSError:
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=self.context.target_id
                ) from None
        except OSError:
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=self.context.target_id
            ) from None
        locked = False
        try:
            try:
                if created:
                    os.fchmod(descriptor, 0o600)
                info = os.fstat(descriptor)
            except OSError:
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=self.context.target_id
                ) from None
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=self.context.target_id
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError:
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=self.context.target_id
                ) from None
            locked = True
            yield
        finally:
            release_failed = False
            try:
                if locked:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        release_failed = True
            finally:
                try:
                    os.close(descriptor)
                except OSError:
                    release_failed = True
            if release_failed:
                raise RegistrarError(
                    ReasonCode.WRITER_RELEASE_FAILED,
                    target_id=self.context.target_id,
                ) from None
