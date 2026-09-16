# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""No-follow, descriptor-relative source capture; imports only the standard library.

``read_confined(root, relative)`` is the shared live-hash interface. Staging uses
one ``ConfinedRoot`` to retain root identity across its complete capture. No
symlink is resolved, including ancestors of the supplied root. Files must have
one hard link, be regular, and fit MAX_FILE_BYTES. Concurrent mutation fails
closed when observed; a privileged/same-UID attacker able to move open trees or
rewrite inodes is not isolated by filesystem pathname checks alone.
"""
import errno
import os
import stat
from contextlib import contextmanager
from pathlib import Path

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 50000
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _parts(relative, allow_empty=False):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or (not path.parts and not allow_empty):
        raise ValueError("Expected a confined relative path")
    return path.parts


def _identity(info):
    return info.st_dev, info.st_ino


def _version(info):
    return _identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


def _unsafe(message):
    return OSError(errno.EPERM, message)


def _directory_at(parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise _unsafe("Not a physical directory")
    descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
    try:
        if _identity(os.fstat(descriptor)) != _identity(before):
            raise _unsafe("Directory replaced while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


class ConfinedRoot:
    """Pin a physical root and retain its ancestor identities until close."""

    def __init__(self, root):
        self.root = Path(root)
        if ".." in self.root.parts:
            raise ValueError("Root must not contain parent traversal")
        # abspath is lexical, unlike resolve/realpath, which would follow links.
        self.root = Path(os.path.abspath(self.root))
        self._chain = []
        self._anchor = os.open("/", _DIR_FLAGS)
        self._closed = False
        descriptor = self._anchor
        try:
            for name in self.root.parts[1:]:
                child = _directory_at(descriptor, name)
                self._chain.append((descriptor, name, child))
                descriptor = child
            self.fd = descriptor
            self._check()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        if not self._closed:
            self._closed = True
            for _, _, descriptor in reversed(self._chain):
                os.close(descriptor)
            os.close(self._anchor)

    def _check(self, extra=()):
        if self._closed:
            raise _unsafe("Confined root is closed")
        for parent, name, descriptor in (*self._chain, *extra):
            linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(linked.st_mode) or _identity(linked) != _identity(os.fstat(descriptor)):
                raise _unsafe("Physical directory identity changed")

    @contextmanager
    def _directory(self, relative=Path(), create=False):
        parts = _parts(relative, allow_empty=True)
        self._check()
        chain = []
        descriptor = self.fd
        try:
            for name in parts:
                if create:
                    self._check(chain)
                    try:
                        os.mkdir(name, mode=0o755, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = _directory_at(descriptor, name)
                chain.append((descriptor, name, child))
                descriptor = child
            self._check(chain)
            yield descriptor, chain
        finally:
            for _, _, child in reversed(chain):
                os.close(child)

    def validate_directory(self, relative=Path()):
        """Reject unsafe directory components without listing their contents."""
        with self._directory(relative):
            pass

    def is_file(self, relative):
        """Probe a candidate without following links; missing paths return false."""
        parts = _parts(relative)
        try:
            with self._directory(Path(*parts[:-1])) as (parent, chain):
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                self._check(chain)
                if stat.S_ISDIR(info.st_mode):
                    return False
                self._regular(info)
                return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _unsafe("Source must be a singly-linked regular file")
        if info.st_size > MAX_FILE_BYTES:
            raise _unsafe("Source exceeds capture limit")

    def read(self, relative):
        """Capture bounded bytes once, rejecting observed replacement or mutation."""
        parts = _parts(relative)
        with self._directory(Path(*parts[:-1])) as (parent, chain):
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            self._regular(before)
            descriptor = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            try:
                opened = os.fstat(descriptor)
                self._regular(opened)
                if _version(before) != _version(opened):
                    raise _unsafe("Source replaced while opening")
                self._check(chain)
                # The bound is fixed before reading: a growing source cannot
                # extend this loop indefinitely, and no validation re-read occurs.
                remaining = opened.st_size + 1
                chunks = []
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                after = os.fstat(descriptor)
                linked = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                self._check(chain)
                if len(data) != opened.st_size or _version(after) != _version(opened) or _version(linked) != _version(opened):
                    raise _unsafe("Source changed during capture")
                return data
            finally:
                os.close(descriptor)

    def files(self, relative, suffixes, recursive=False):
        """List only safe files, validating directories before descending."""
        found = []
        count = 0
        def visit(folder):
            nonlocal count
            with self._directory(folder) as (descriptor, chain):
                names = sorted(os.listdir(descriptor))
                count += len(names)
                if count > MAX_ENTRIES:
                    raise _unsafe("Source tree exceeds traversal limit")
                children = []
                for name in names:
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if recursive:
                            children.append(folder / name)
                    elif stat.S_ISREG(info.st_mode):
                        if Path(name).suffix in suffixes:
                            self._regular(info)
                            found.append(folder / name)
                    else:
                        raise _unsafe("Unsafe source tree entry")
                self._check(chain)
            for child in children:
                visit(child)
        visit(Path(relative))
        return found

    def write_new(self, relative, data):
        """Create a non-replacing read-only file below this pinned destination."""
        parts = _parts(relative)
        with self._directory(Path(*parts[:-1]), create=True) as (parent, chain):
            self._check(chain)
            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o444, dir_fd=parent)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise _unsafe("Incomplete stage write")
                    view = view[written:]
                os.fchmod(descriptor, 0o444)
                self._check(chain)
                linked = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(linked.st_mode) or _identity(linked) != _identity(os.fstat(descriptor)):
                    raise _unsafe("Destination replaced during write")
            finally:
                os.close(descriptor)


def read_confined(root: Path, relative: Path | str) -> bytes:
    """Read one regular file without following root, ancestor, or leaf links."""
    with ConfinedRoot(root) as source:
        return source.read(relative)


@contextmanager
def new_destination(destination):
    """Create a fresh stage root; existing destinations are always collisions."""
    destination = Path(destination)
    if not destination.name or ".." in destination.parts:
        raise ValueError("Expected a new destination directory")
    with ConfinedRoot(destination.parent) as parent:
        parent._check()
        os.mkdir(destination.name, mode=0o755, dir_fd=parent.fd)
        created = os.stat(destination.name, dir_fd=parent.fd, follow_symlinks=False)
        with ConfinedRoot(destination) as output:
            if not stat.S_ISDIR(created.st_mode) or _identity(created) != _identity(os.fstat(output.fd)):
                raise _unsafe("Destination root replaced")
            yield output
            output._check()
