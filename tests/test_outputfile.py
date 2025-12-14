#
# MIT License
#
# Copyright (c) 2023-2025 nbiotcloud
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""Testing."""

import re
import stat
import time

from contextlib_chdir import chdir
from pytest import approx, fixture, mark, raises

from outputfile import Existing, State, open_

SLEEP = 0.2
WORLD = """
Hello World.
"""
MARS = """
Hello Mars.
"""
LINE = "One-Line"

BYTES = bytes(range(10))
OTHERBYTES = bytes(range(15))


def cmp_mtime(mtime0, mtime1):
    """Compare Modification Times."""
    # Hack, to resolve floating round issue
    return abs(mtime1 - mtime0) == approx(0)


@fixture
def filepath(tmp_path):
    """Return Filepath In Temporary Directory."""
    yield tmp_path / "file.txt"


@fixture
def subfilepath(filepath):
    """File Within not existing subdirectory."""
    yield filepath.parent / "sub" / "file.txt"


@fixture
def tracker():
    """Tracker."""
    return []


@fixture
def pre_post(tracker):
    """Pre."""

    def pre_create(filepath):
        tracker.append(("pre_create", filepath))

    def post_create(filepath):
        tracker.append(("post_create", filepath))

    def pre_update(filepath):
        tracker.append(("pre_update", filepath))

    def post_update(filepath):
        tracker.append(("post_update", filepath))

    return {
        "pre_create": pre_create,
        "post_create": post_create,
        "pre_update": pre_update,
        "post_update": post_update,
    }


def test_attrs(filepath):
    """OutputFile attributes."""
    with open_(filepath) as file:
        # assert file.path == filepath
        assert not file.mkdir
        assert file.existing is Existing.KEEP_TIMESTAMP
        assert file.state == State.OPEN


def test_no_update(filepath):
    """Unchanged content shall not modify the timestamp."""
    changes = []

    def diffout(item):
        changes.append(item)

    # First Write
    with open_(filepath, diffout=diffout) as file:
        file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert not changes

    # Successive Writes
    for _ in range(3):
        time.sleep(SLEEP)

        with open_(filepath, diffout=diffout) as file:
            file.write(WORLD)
        assert cmp_mtime(mtime, filepath.stat().st_mtime)
        assert filepath.read_text() == WORLD
        assert file.state == State.IDENTICAL
        assert not changes


def test_update(filepath):
    """Every content change has to trigger a file update."""
    changes = []

    def diffout(item):
        changes.append(item)

    # First Write
    with open_(filepath, diffout=diffout) as file:
        file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert not changes

    time.sleep(SLEEP)

    # Second Write
    with open_(filepath, diffout=diffout) as file:
        file.write(MARS)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == MARS
    assert file.state == State.UPDATED
    assert changes == ["--- \n+++ \n@@ -1,2 +1,2 @@\n \n-Hello World.\n+Hello Mars.\n"]

    time.sleep(SLEEP)
    changes.clear()

    # Third Write
    with open_(filepath, diffout=diffout) as file:
        file.write(WORLD)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == WORLD
    assert file.state == State.UPDATED
    assert changes == ["--- \n+++ \n@@ -1,2 +1,2 @@\n \n-Hello Mars.\n+Hello World.\n"]


def test_update_pre_post(filepath, tracker, pre_post):
    """Every content change has to trigger a file update."""
    # First Write
    with open_(filepath, **pre_post) as file:
        file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert tracker == [
        ("pre_create", filepath),
        ("post_create", filepath),
    ]

    time.sleep(SLEEP)

    # Second Write
    with open_(filepath, **pre_post) as file:
        file.write(MARS)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == MARS
    assert file.state == State.UPDATED
    assert tracker == [
        ("pre_create", filepath),
        ("post_create", filepath),
        ("pre_update", filepath),
        ("post_update", filepath),
    ]

    time.sleep(SLEEP)

    # Third Write
    with open_(filepath, **pre_post) as file:
        file.write(WORLD)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == WORLD
    assert file.state == State.UPDATED
    assert tracker == [
        ("pre_create", filepath),
        ("post_create", filepath),
        ("pre_update", filepath),
        ("post_update", filepath),
        ("pre_update", filepath),
        ("post_update", filepath),
    ]


def test_update_singleline(filepath):
    """Content without newline and fast."""
    with open_(filepath) as file:
        file.write("foo")
    assert file.state == State.CREATED
    assert filepath.read_text() == "foo"

    with open_(filepath) as file:
        file.write("foo")
    assert file.state == State.IDENTICAL
    assert filepath.read_text() == "foo"

    with open_(filepath) as file:
        file.write("barz")
        file.flush()
    assert file.state == State.UPDATED
    assert filepath.read_text() == "barz"


class MyException(Exception):  # noqa: N818
    """Dummy Exception."""


@mark.parametrize("existing", [Existing.KEEP_TIMESTAMP, Existing.KEEP])
def test_exception(filepath, existing):
    """An incomplete file caused by an exception, has to be ignored."""
    state = {
        Existing.KEEP_TIMESTAMP: State.FAILED,
        Existing.KEEP: State.EXISTING,
    }[existing]
    # First Write
    with open_(filepath) as file:
        file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED

    time.sleep(SLEEP)

    # Second Write
    try:
        with open_(filepath, existing=existing) as file:
            file.write(MARS)
            raise MyException
    except MyException:
        pass
    assert filepath.read_text() == WORLD
    assert cmp_mtime(mtime, filepath.stat().st_mtime)
    assert file.state == state


def test_close(filepath):
    """Test OutputFile with explicit close()."""
    file = open_(filepath)
    file.write(WORLD)
    assert file.state == State.OPEN
    assert not file.closed
    file.close()
    assert file.closed
    assert file.state == State.CREATED
    file.close()
    assert file.closed
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED


def test_close_pre_post(filepath, tracker, pre_post):
    """Test OutputFile with explicit close()."""
    file = open_(filepath, **pre_post)
    assert tracker == []
    file.write(WORLD)
    assert file.state == State.OPEN
    assert not file.closed
    file.close()
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]
    assert file.closed
    assert file.state == State.CREATED
    file.close()
    assert file.closed
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]


def test_write_closed(filepath):
    """Writing a closed file shall raise an Exception."""
    file = open_(filepath)
    file.write(WORLD)
    file.close()
    assert file.state == State.CREATED

    match = re.escape("I/O Error. Write on closed file.")
    with raises(ValueError, match=match):
        file.write(WORLD)
    assert file.state == State.CREATED


def test_mkdir(subfilepath):
    """Create output directory."""
    match = re.escape(f"Output directory '{subfilepath.parent}' does not exists.")
    with raises(FileNotFoundError, match=match):
        open_(subfilepath)

    with open_(subfilepath, mkdir=True) as file:
        file.write(WORLD)
    assert subfilepath.read_text() == WORLD


def test_existing_error(filepath):
    """existing=Existing.ERROR."""
    # First
    with open_(filepath, existing=Existing.ERROR) as file:
        file.write(WORLD)
    assert file.state == State.CREATED

    # Failing second
    with raises(FileExistsError):
        with open_(filepath, existing=Existing.ERROR) as file:
            file.write(MARS)
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED


def test_existing_error_pre_post(filepath, tracker, pre_post):
    """existing=Existing.ERROR."""
    # First
    with open_(filepath, existing=Existing.ERROR, **pre_post) as file:
        file.write(WORLD)
    assert file.state == State.CREATED
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]

    # Failing second
    with raises(FileExistsError):
        with open_(filepath, existing=Existing.ERROR, **pre_post) as file:
            file.write(MARS)
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]


def test_existing_keep(filepath):
    """existing=Existing.KEEP."""
    # First
    with open_(filepath, existing=Existing.KEEP) as file:
        file.write(WORLD)
    assert file.state == State.CREATED

    # Second, ignored.
    with open_(filepath, existing=Existing.KEEP) as file:
        file.write(MARS)
    assert filepath.read_text() == WORLD
    assert file.state == State.EXISTING


def test_existing_keep_pre_post(filepath, tracker, pre_post):
    """existing=Existing.KEEP."""
    # First
    with open_(filepath, existing=Existing.KEEP, **pre_post) as file:
        file.write(WORLD)
        assert tracker == [("pre_create", filepath)]

    assert file.state == State.CREATED
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]

    # Second, ignored.
    with open_(filepath, existing=Existing.KEEP, **pre_post) as file:
        file.write(MARS)
    assert filepath.read_text() == WORLD
    assert file.state == State.EXISTING
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]


def test_existing_overwrite(filepath):
    """existing=Existing.OVERWRITE."""
    # First Write
    with open_(filepath, existing=Existing.OVERWRITE) as file:
        file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED

    time.sleep(SLEEP)

    # Second Write
    with open_(filepath, existing=Existing.OVERWRITE) as file:
        file.write(WORLD)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == WORLD
    assert file.state == State.OVERWRITTEN


def test_existing_overwrite_pre_post(filepath, tracker, pre_post):
    """existing=Existing.OVERWRITE."""
    # First Write
    with open_(filepath, existing=Existing.OVERWRITE, **pre_post) as file:
        file.write(WORLD)
        assert tracker == [("pre_create", filepath)]
    assert tracker == [("pre_create", filepath), ("post_create", filepath)]
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED

    time.sleep(SLEEP)

    # Second Write
    with open_(filepath, existing=Existing.OVERWRITE, **pre_post) as file:
        file.write(WORLD)
        assert tracker == [("pre_create", filepath), ("post_create", filepath), ("pre_update", filepath)]
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == WORLD
    assert file.state == State.OVERWRITTEN
    assert tracker == [
        ("pre_create", filepath),
        ("post_create", filepath),
        ("pre_update", filepath),
        ("post_update", filepath),
    ]


def test_existing_overwrite_str(filepath):
    """existing='overwrite'."""
    # First Write
    with chdir(filepath.parent):
        with open_(filepath.name, existing="overwrite") as file:
            file.write(WORLD)
    mtime = filepath.stat().st_mtime
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED

    time.sleep(SLEEP)

    # Second Write
    with open_(filepath, existing=Existing.OVERWRITE) as file:
        file.write(WORLD)
    assert not cmp_mtime(mtime, filepath.stat().st_mtime)
    assert filepath.read_text() == WORLD
    assert file.state == State.OVERWRITTEN


def test_flush(filepath):
    """Flushing."""
    with open_(filepath) as file:
        file.write(WORLD)
        file.flush()
    assert filepath.read_text() == WORLD
    file.flush()
    assert filepath.read_text() == WORLD


@mark.parametrize("mode", ("", "w", "t"))
@mark.parametrize("diffout", (None, print))
def test_mode_text(filepath, mode, diffout, capsys):
    """Mode Text."""
    with open_(filepath, mode=mode) as file:
        file.write(WORLD)
    assert filepath.read_text() == WORLD
    assert file.state == State.CREATED
    assert not capsys.readouterr().out
    with open_(filepath, mode=mode, diffout=diffout) as file:
        file.write(MARS)
    assert file.mode in ("w", "wt")
    assert filepath.read_text() == MARS
    diff = "--- \n+++ \n@@ -1,2 +1,2 @@\n \n-Hello World.\n+Hello Mars.\n\n" if diffout else ""
    assert capsys.readouterr().out == diff
    assert file.state == State.UPDATED


@mark.parametrize("mode", ("b", "wb"))
@mark.parametrize("diffout", (None, print))
def test_mode_binary(filepath, mode, diffout, capsys):
    """Mode Binary."""
    with open_(filepath, mode=mode) as file:
        file.write(BYTES)
    assert filepath.read_bytes() == BYTES
    assert not capsys.readouterr().out
    assert file.state == State.CREATED
    with open_(filepath, mode=mode, diffout=diffout) as file:
        file.write(OTHERBYTES)
    assert file.mode == "wb"
    assert filepath.read_bytes() == OTHERBYTES
    assert not capsys.readouterr().out
    assert file.state == State.UPDATED


@mark.parametrize("mode", ("r", "a", "+"))
def test_mode_invalid(filepath, mode):
    """Invalid Mode."""
    with raises(ValueError, match=re.escape(f"mode {mode!r} is not supported ({mode!r}).")):
        with open_(filepath, mode=mode) as file:
            file.write(WORLD)
    assert not filepath.exists()


@mark.parametrize("encoding", ("utf-8", "latin-1"))
def test_encoding(filepath, encoding):
    """Encoding."""
    with open_(filepath, encoding=encoding) as file:
        file.write(LINE)
    assert filepath.read_text() == LINE
    assert filepath.read_bytes() == LINE.encode(encoding)


@mark.parametrize("existing", ("keep_timestamp", "overwrite"))
def test_permission_error(filepath, existing):
    """Permission Error."""
    filepath.touch()
    filepath.chmod(filepath.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP)
    with raises(PermissionError):
        with open_(filepath, existing=existing) as file:
            file.write("test")
