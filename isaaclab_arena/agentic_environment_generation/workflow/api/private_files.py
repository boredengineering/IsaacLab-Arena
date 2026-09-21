# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded owner-private local configuration IO; never workflow persistence."""

import fcntl
import json
import math
import os
import secrets
import stat
from contextlib import contextmanager, suppress
from pathlib import PurePosixPath


class PrivateFileError(ValueError):
    """Static refusal, including writes whose durability is unknown."""


def canonical_path(value):
    if (
        type(value) is not str
        or not value.startswith("/")
        or value == "/"
        or len(value.encode("utf-8")) > 4096
        or len(value.split("/")) > 65
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or str(PurePosixPath(value)) != value
        or ".." in value.split("/")
        or value.startswith("//")
    ):
        raise PrivateFileError("Invalid private path")
    return value


def decode(raw, limit):
    if type(raw) is not bytes or len(raw) > limit:
        raise PrivateFileError("Invalid private document")
    text = raw.decode("utf-8")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                raise PrivateFileError("Invalid private document")
        elif char in "]}":
            depth -= 1

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PrivateFileError("Invalid private document")
            result[key] = value
        return result

    def reject(_):
        raise PrivateFileError("Invalid private document")

    def number(raw):
        value = float(raw)
        if not math.isfinite(value):
            reject(None)
        return value

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject, parse_float=number)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise PrivateFileError("Invalid private document")
    return value


def _regular(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or info.st_gid != os.getgid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise PrivateFileError("Invalid private file")


class Directory:
    """Hold a no-follow directory capability; reject existing conflicts."""

    def __init__(self, path, *, create=False):
        self.path = canonical_path(path)
        self.fd = None
        if os.getuid() == 0:
            raise PrivateFileError("Nonroot operator required")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        parts = self.path.split("/")[1:]
        try:
            for index, part in enumerate(parts):
                created = False
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                except FileNotFoundError:
                    if not create or index != len(parts) - 1:
                        raise
                    previous = os.umask(0o077)
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    finally:
                        os.umask(previous)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    created = True
                try:
                    if created:
                        os.fchmod(child, 0o700)
                        os.fsync(child)
                        os.fsync(fd)
                    info = os.fstat(child)
                    if info.st_uid not in (0, os.getuid()) or (
                        info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
                    ):
                        raise PrivateFileError("Uncontrolled private path")
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_gid != os.getgid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PrivateFileError("Invalid private directory")
            self.fd = fd
            self.identity = info.st_dev, info.st_ino
        except BaseException:
            os.close(fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)
        self.fd = None

    def check(self):
        with Directory(self.path) as current:
            if current.identity != self.identity:
                raise PrivateFileError("Private directory changed")

    @staticmethod
    def name(name):
        if type(name) is not str or not name or name in (".", "..") or "/" in name or len(name) > 128:
            raise PrivateFileError("Invalid private name")
        return name

    def open_file(self, name, *, create=False):
        self.check()
        self.name(name)
        flags = os.O_RDWR if create else os.O_RDONLY
        flags |= os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        made = False
        if create:
            try:
                fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=self.fd)
                made = True
            except FileExistsError:
                fd = os.open(name, flags, dir_fd=self.fd)
        else:
            fd = os.open(name, flags, dir_fd=self.fd)
        try:
            if made:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
                os.fsync(self.fd)
            _regular(os.fstat(fd))
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, name, limit):
        fd = self.open_file(name)
        try:
            if os.fstat(fd).st_size > limit:
                raise PrivateFileError("Private file too large")
            data = bytearray()
            while len(data) <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > limit:
                raise PrivateFileError("Private file too large")
            return bytes(data)
        finally:
            os.close(fd)

    @contextmanager
    def lease(self, name):
        fd = self.open_file(name, create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield fd
        finally:
            os.close(fd)

    def write(self, name, raw, *, replace=False):
        """Caller holds the exact writer lease; a failed fsync stays uncertain."""
        self.check()
        self.name(name)
        if type(raw) is not bytes or len(raw) > 256 * 1024:
            raise PrivateFileError("Invalid private document")
        try:
            existing = self.open_file(name)
        except FileNotFoundError:
            if replace:
                raise
        else:
            os.close(existing)
            if not replace:
                raise FileExistsError("Private file already exists")
        temporary = ".pending-" + secrets.token_hex(16)
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd
        )
        try:
            os.fchmod(fd, 0o600)
            remaining = memoryview(raw)
            while remaining:
                count = os.write(fd, remaining)
                if count <= 0:
                    raise PrivateFileError("Private write incomplete")
                remaining = remaining[count:]
            os.fsync(fd)
            self.check()
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            os.close(fd)
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=self.fd)


def read_private(path, limit):
    path = PurePosixPath(canonical_path(path))
    with Directory(str(path.parent)) as directory:
        return directory.read(path.name, limit)
