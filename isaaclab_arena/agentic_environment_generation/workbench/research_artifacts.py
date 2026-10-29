# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private immutable bytes for the Linux-local filesystem deployment.

Callers MUST protect/redact data before calling stage; JSON bounds and filename
checks are not secret detection. This is not a registry transaction or an ACL
boundary against another process running as the same trusted OS user.

Limits: 1–16 flat .yaml/.json payload files, 2 MiB per file, 8 MiB total.
Payload bytes are opaque: they are not parsed, validated as YAML/JSON, or redacted.
Binding is finite JSON: 32 KiB canonical bytes, depth 16, 4096 values, 8192
characters per string, 128 per key, signed 64-bit integers. Manifests are schema
1, at most 64 KiB, with SHA-256 of canonical JSON excluding the digest field.
IDs (including family and version) are case-sensitive ASCII strings matching
[A-Za-z0-9][A-Za-z0-9_-]{0,127}; paths and names are never case-folded.
Incomplete staging is retained and rejected on retry, never repaired. A failed
promotion fsync may leave a complete final directory; only a subsequent fully
verified, successfully synced retry reconciles it. Registry commits are external.
"""

import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat


class ArtifactError(ValueError):
    """Safe artifact rejection; messages never include paths or payloads."""


class SafeBusy(RuntimeError):
    """A cooperative local writer is active; caller may explicitly retry later."""


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ArtifactError("Invalid artifact identifier")
    return value


def _canonical(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (ValueError, TypeError, RecursionError):
        raise ArtifactError("Invalid artifact JSON") from None


def _filename(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.(yaml|json)", name):
        raise ArtifactError("Invalid artifact filename")
    if name == "manifest.json" or re.search(r"(?i)(credential|secret|private|password|token|api[_-]?key)", name):
        raise ArtifactError("Private artifact filename rejected")
    return name


def _binding(value):
    budget = [4096]

    def walk(item, depth):
        budget[0] -= 1
        if budget[0] < 0 or depth > 16:
            raise ArtifactError("Artifact JSON exceeds bounds")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    raise ArtifactError("Invalid artifact JSON key")
                walk(child, depth + 1)
        elif type(item) is list:
            for child in item:
                walk(child, depth + 1)
        elif type(item) is str:
            if len(item) > 8192:
                raise ArtifactError("Artifact JSON exceeds bounds")
        elif item is not None and type(item) not in (int, float, bool):
            raise ArtifactError("Invalid artifact JSON value")
        elif type(item) is int and not -(2**63) <= item < 2**63:
            raise ArtifactError("Artifact JSON integer exceeds bounds")

    if type(value) is not dict:
        raise ArtifactError("Invalid artifact binding")
    walk(value, 0)
    encoded = _canonical(value)
    if len(encoded) > 32768:
        raise ArtifactError("Artifact binding exceeds bounds")
    return json.loads(encoded)


def _check(fd, directory=False, ancestor=False):
    info = os.fstat(fd)
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    # Sticky ancestors such as /tmp are allowed, never managed directories.
    writable = info.st_mode & 0o002 and not (ancestor and info.st_mode & stat.S_ISVTX)
    if not valid or writable:
        raise ArtifactError("Unsafe artifact filesystem entry")


@contextlib.contextmanager
def _directory(parent, name):
    if parent is None:
        raise ArtifactError("Artifact area is closed")
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        _check(fd, directory=True)
        yield fd
    finally:
        os.close(fd)


def _root(path, create):
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or any(p in (".", "..") for p in raw.split("/")):
        raise ArtifactError("Invalid artifact root")
    parts = raw.split("/")
    fd = os.open("/" if raw.startswith("/") else ".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = [p for p in parts if p]
        if not parts:
            raise ArtifactError("Invalid artifact root")
        for index, part in enumerate(parts):
            _check(fd, directory=True, ancestor=True)
            if create and index == len(parts) - 1:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=fd,
            )
            os.close(fd)
            fd = next_fd
        _check(fd, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write(parent, name, data):
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=parent,
    )
    try:
        _check(fd)
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise ArtifactError("Artifact write failed")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(parent, name, limit, sync=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        _check(fd)
        if os.fstat(fd).st_size > limit:
            raise ArtifactError("Artifact exceeds bounds")
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        _check(fd)
        if len(data) > limit:
            raise ArtifactError("Artifact exceeds bounds")
        if sync:
            os.fsync(fd)
        return data
    finally:
        os.close(fd)


def _rename_noreplace(source_fd, source, target_fd, target):
    """Linux-only atomic no-clobber rename; there is no unsafe fallback."""
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise ArtifactError("Atomic artifact promotion unavailable")
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(source_fd, source.encode(), target_fd, target.encode(), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, "Artifact target exists")
        raise ArtifactError("Atomic artifact promotion failed")


class ArtifactArea:
    """An explicitly bound area; close it or use it as a context manager."""

    MARKER = ".artifact-area.json"

    def __init__(self, *args, **kwargs):
        raise ArtifactError("Use ArtifactArea.create or ArtifactArea.open")

    @classmethod
    def create(cls, root, *, store_id, registry_id):
        """Initialize only a missing root or an existing empty root."""
        return cls._load(root, store_id, registry_id, True)

    @classmethod
    def open(cls, root, *, store_id, registry_id):
        """Validate an existing area without creating or adopting anything."""
        return cls._load(root, store_id, registry_id, False)

    @classmethod
    def _load(cls, root, store_id, registry_id, create):
        marker = {
            "schema": 1,
            "store_id": _id(store_id),
            "registry_id": _id(registry_id),
        }
        fd = None
        try:
            fd = _root(root, create)
            if create:
                if os.listdir(fd):
                    raise ArtifactError("Artifact root must be empty")
                for name in ("staging", "final"):
                    os.mkdir(name, 0o700, dir_fd=fd)
                    with _directory(fd, name) as child:
                        os.fsync(child)
                _write(fd, cls.MARKER, _canonical(marker))
                os.fsync(fd)
            if set(os.listdir(fd)) != {cls.MARKER, "staging", "final"}:
                raise ArtifactError("Invalid artifact root layout")
            if _read(fd, cls.MARKER, 4096) != _canonical(marker):
                raise ArtifactError("Artifact area binding mismatch")
            for name in ("staging", "final"):
                with _directory(fd, name):
                    pass
            area = object.__new__(cls)
            area._fd = fd
            area.store_id = store_id
            area.registry_id = registry_id
            with area.writer_lock():
                area._validate_tree()
            return area
        except BaseException as error:
            if fd is not None:
                os.close(fd)
            if not isinstance(error, (OSError, ValueError, RecursionError)):
                raise
            raise ArtifactError("Artifact area initialization rejected") from None

    def _validate_tree(self):
        with _directory(self._fd, "staging") as staging:
            for reservation in os.listdir(staging):
                _id(reservation)
                with _directory(staging, reservation) as directory:
                    names = os.listdir(directory)
                    if "manifest.json" in names:
                        manifest = json.loads(_read(directory, "manifest.json", 65536))
                        self._validate_manifest(manifest)
                        if manifest.get("reservation_id") != reservation:
                            raise ArtifactError("Artifact reservation mismatch")
                        self._verify_fd(directory, manifest)
                    else:
                        # Interrupted stages may remain, but cannot be promoted or repaired.
                        if len(names) > 16:
                            raise ArtifactError("Invalid incomplete artifact")
                        total = 0
                        for name in names:
                            _filename(name)
                            total += len(_read(directory, name, 2 * 1024 * 1024))
                        if total > 8 * 1024 * 1024:
                            raise ArtifactError("Invalid incomplete artifact")
        with _directory(self._fd, "final") as final:
            for family in os.listdir(final):
                _id(family)
                with _directory(final, family) as parent:
                    for version in os.listdir(parent):
                        _id(version)
                        with _directory(parent, version) as directory:
                            manifest = json.loads(_read(directory, "manifest.json", 65536))
                            self._verify_fd(directory, manifest)

    def _manifest(self, reservation_id, files, binding):
        binding = _binding(binding)
        if type(files) is not dict or not 1 <= len(files) <= 16:
            raise ArtifactError("Invalid artifact file count")
        total = 0
        for name, data in files.items():
            _filename(name)
            if type(data) is not bytes or len(data) > 2 * 1024 * 1024:
                raise ArtifactError("Invalid artifact bytes")
            total += len(data)
        if total > 8 * 1024 * 1024:
            raise ArtifactError("Artifact total exceeds bounds")
        body = {
            "schema": 1,
            "store_id": self.store_id,
            "registry_id": self.registry_id,
            "reservation_id": _id(reservation_id),
            "binding": binding,
            "files": {
                name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(files.items())
            },
        }
        body["digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return json.loads(_canonical(body))

    def _validate_manifest(self, manifest):
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema",
            "store_id",
            "registry_id",
            "reservation_id",
            "binding",
            "files",
            "digest",
        }:
            raise ArtifactError("Invalid artifact manifest")
        if (
            type(manifest["schema"]) is not int
            or manifest["schema"] != 1
            or manifest["store_id"] != self.store_id
            or manifest["registry_id"] != self.registry_id
        ):
            raise ArtifactError("Artifact manifest binding mismatch")
        _id(manifest["reservation_id"])
        _binding(manifest["binding"])
        entries = manifest["files"]
        if type(entries) is not dict or not 1 <= len(entries) <= 16:
            raise ArtifactError("Invalid artifact file count")
        total = 0
        for name, entry in entries.items():
            _filename(name)
            if type(entry) is not dict or set(entry) != {"size", "sha256"}:
                raise ArtifactError("Invalid artifact file metadata")
            if type(entry["size"]) is not int or not 0 <= entry["size"] <= 2 * 1024 * 1024:
                raise ArtifactError("Invalid artifact file size")
            if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise ArtifactError("Invalid artifact file hash")
            total += entry["size"]
        if total > 8 * 1024 * 1024 or len(_canonical(manifest)) > 65536:
            raise ArtifactError("Artifact manifest exceeds bounds")
        body = {key: value for key, value in manifest.items() if key != "digest"}
        if hashlib.sha256(_canonical(body)).hexdigest() != manifest["digest"]:
            raise ArtifactError("Artifact manifest digest mismatch")
        return manifest

    def _verify_fd(self, fd, manifest, sync=False):
        self._validate_manifest(manifest)
        if _read(fd, "manifest.json", 65536, sync=sync) != _canonical(manifest):
            raise ArtifactError("Artifact manifest mismatch")
        if set(os.listdir(fd)) != set(manifest["files"]) | {"manifest.json"}:
            raise ArtifactError("Artifact file set mismatch")
        files = {name: _read(fd, name, entry["size"], sync=sync) for name, entry in manifest["files"].items()}
        if self._manifest(manifest["reservation_id"], files, manifest["binding"]) != manifest:
            raise ArtifactError("Artifact bytes mismatch")
        return files

    @contextlib.contextmanager
    def writer_lock(self):
        """Take a nonblocking Linux flock on the validated private schema marker.

        Each acquisition owns a fresh descriptor, including on the same area object.
        The immutable marker doubles as lockfile: reads create no filesystem entries.
        """
        if self._fd is None:
            raise ArtifactError("Artifact area is closed")
        fd = None
        try:
            fd = os.open(self.MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._fd)
            _check(fd)
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ArtifactError("Unsafe artifact lockfile")
            expected = _canonical({
                "schema": 1,
                "store_id": self.store_id,
                "registry_id": self.registry_id,
            })
            if os.read(fd, 4097) != expected:
                raise ArtifactError("Artifact lock binding mismatch")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SafeBusy("Research store writer busy") from None
            yield
        except OSError:
            raise ArtifactError("Artifact writer lock failed") from None
        finally:
            if fd is not None:
                os.close(fd)

    def expected_manifest(self, reservation_id, files: dict[str, bytes], binding: dict) -> dict:
        """Compute a bounded expected manifest without creating another artifact copy."""
        return self._manifest(reservation_id, files, binding)

    def read_final_manifest(self, family, version, *, binding):
        """Read and verify one exact final artifact without adopting staging files.

        Args:
            family: Exact retained artifact family.
            version: Exact retained version identity, not a search prefix.
            binding: Expected binding from the authoritative caller.

        Returns:
            The bounded manifest verified against its actual payload bytes.
        """
        _id(family)
        _id(version)
        binding = _binding(binding)
        try:
            with self.writer_lock(), _directory(self._fd, "final") as final:
                with _directory(final, family) as parent, _directory(parent, version) as directory:
                    manifest = json.loads(_read(directory, "manifest.json", 65536))
                    self._verify_fd(directory, manifest)
                    if manifest["reservation_id"] != version or _canonical(manifest["binding"]) != _canonical(binding):
                        raise ArtifactError("Exact artifact recovery binding required")
                    return manifest
        except (OSError, ValueError, RecursionError):
            raise ArtifactError("Artifact recovery read rejected") from None

    def has_final(self, family, version) -> bool:
        """Check directory presence only; corrupt or unsafe entries are never absence.

        A True result is not verification: callers must verify the expected manifest.
        """
        _id(family)
        _id(version)
        try:
            with _directory(self._fd, "final") as final:
                if family not in os.listdir(final):
                    return False
                with _directory(final, family) as parent:
                    if version not in os.listdir(parent):
                        return False
                    with _directory(parent, version):
                        return True
        except OSError:
            raise ArtifactError("Artifact final lookup failed") from None

    def stage(self, reservation_id, files: dict[str, bytes], binding: dict) -> dict:
        """Write protected bytes once; exact verified retries return the same manifest.

        Binding is caller-supplied source-candidate/attempt metadata, preserved
        literally. It is not authorization evidence and is not secret-redacted.
        """
        manifest = self._manifest(reservation_id, files, binding)
        try:
            with _directory(self._fd, "staging") as staging:
                try:
                    os.mkdir(reservation_id, 0o700, dir_fd=staging)
                except FileExistsError:
                    with _directory(staging, reservation_id) as existing:
                        self._verify_fd(existing, manifest, sync=True)
                        os.fsync(existing)
                    os.fsync(staging)
                    return manifest
                with _directory(staging, reservation_id) as directory:
                    for name, data in files.items():
                        _write(directory, name, data)
                    _write(directory, "manifest.json", _canonical(manifest))
                    os.fsync(directory)
                os.fsync(staging)
            return manifest
        except OSError:
            raise ArtifactError("Artifact staging failed") from None

    def promote(self, reservation_id, family, version, manifest) -> str:
        """Atomically publish to final/<family>/<version>; all IDs are literal strings."""
        _id(reservation_id)
        _id(family)
        _id(version)
        self._validate_manifest(manifest)
        if manifest["reservation_id"] != reservation_id:
            raise ArtifactError("Artifact reservation mismatch")
        relative = f"final/{family}/{version}"
        try:
            with (
                _directory(self._fd, "staging") as staging,
                _directory(self._fd, "final") as final,
            ):
                try:
                    os.mkdir(family, 0o700, dir_fd=final)
                except FileExistsError:
                    pass
                with _directory(final, family) as parent:
                    try:
                        with _directory(parent, version) as target:
                            self._verify_fd(target, manifest, sync=True)
                            os.fsync(target)
                    except FileNotFoundError:
                        with _directory(staging, reservation_id) as source:
                            self._verify_fd(source, manifest, sync=True)
                            os.fsync(source)
                        try:
                            _rename_noreplace(staging, reservation_id, parent, version)
                        except FileExistsError:
                            with _directory(parent, version) as target:
                                self._verify_fd(target, manifest, sync=True)
                                os.fsync(target)
                    os.fsync(parent)
                os.fsync(final)
                os.fsync(staging)
                os.fsync(self._fd)
            return relative
        except OSError:
            raise ArtifactError("Artifact promotion failed") from None

    def verify(self, relative_directory, manifest) -> dict[str, bytes]:
        """Return all bounded file bytes only after complete manifest/hash verification."""
        self._validate_manifest(manifest)
        if not isinstance(relative_directory, str):
            raise ArtifactError("Invalid artifact directory")
        parts = relative_directory.split("/")
        if len(parts) != 3 or parts[0] != "final":
            raise ArtifactError("Invalid artifact directory")
        _id(parts[1])
        _id(parts[2])
        try:
            with (
                _directory(self._fd, "final") as final,
                _directory(final, parts[1]) as family,
            ):
                with _directory(family, parts[2]) as directory:
                    return self._verify_fd(directory, manifest)
        except OSError:
            raise ArtifactError("Artifact verification failed") from None

    def read_file(self, relative_directory, manifest, name) -> bytes:
        """Verify the entire artifact and return the named file's exact bytes."""
        files = self.verify(relative_directory, manifest)
        if name not in files:
            raise ArtifactError("Unknown artifact file")
        return files[name]

    def close(self):
        """Release the root descriptor; repeated close is harmless."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
