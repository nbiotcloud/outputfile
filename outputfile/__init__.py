#
# MIT License
#
# Copyright (c) 2023 nbiotcloud
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
"""
Timestamp Preserving Output File Writer.

``outputfile.open_`` behaves identical to ``open(..., mode="w")``:

>>> from outputfile import open_
>>> from pathlib import Path
>>> filepath = Path('file.txt')
>>> with open_(filepath) as file:
...     file.write("foo")

but the timestamp stays the same, if the file content did not change:

>>> mtime = filepath.stat().st_mtime
>>> with open_(filepath) as file:
...     file.write("foo")
>>> mtime - filepath.stat().st_mtime
0.0


The ``state`` attribute details the file handling status:

>>> otherpath = Path('other.txt')
>>> # first write
>>> with open_(otherpath) as file:
...     file.write("foo")
>>> file.state.name
'CREATED'
>>> # same write
>>> with open_(otherpath) as file:
...     file.write("foo")
>>> file.state.name
'IDENTICAL'
>>> # other write
>>> with open_(otherpath) as file:
...     file.write("bar")
>>> file.state.name
'UPDATED'

The argument ``existing`` defines the update strategy and can ``Existing.KEEP`` ...

>>> keep = Path('keep.txt')
>>> # first write
>>> with open_(keep, existing=Existing.KEEP) as file:
...     file.write("foo")
>>> file.state.name
'CREATED'
>>> # same write
>>> with open_(keep, existing=Existing.KEEP) as file:
...     file.write("foo")
>>> file.state.name
'EXISTING'
>>> # other write
>>> with open_(keep, existing=Existing.KEEP) as file:
...     file.write("bar")
>>> file.state.name
'EXISTING'

... or ``Existing.OVERWRITE``

>>> overwrite = Path('overwrite.txt')
>>> # first write
>>> with open_(overwrite, existing=Existing.OVERWRITE) as file:
...     file.write("foo")
>>> file.state.name
'CREATED'
>>> # same write
>>> with open_(overwrite, existing=Existing.OVERWRITE) as file:
...     file.write("foo")
>>> file.state.name
'OVERWRITTEN'
>>> # other write
>>> with open_(overwrite, existing=Existing.OVERWRITE) as file:
...     file.write("bar")
>>> file.state.name
'OVERWRITTEN'
"""
import difflib
import filecmp
import tempfile
from enum import Enum
from os import fdopen as _fdopen
from pathlib import Path
from shutil import copyfile
from typing import Union

__all__ = ["Existing", "State", "open_", "OutputFile"]


class Existing(Enum):

    """Strategy for Handling of existing files."""

    ERROR = "error"
    KEEP = "keep"
    OVERWRITE = "overwrite"
    KEEP_TIMESTAMP = "keep_timestamp"


class State(Enum):

    """File state."""

    OPEN = "OPEN"
    UPDATED = "UPDATED."
    IDENTICAL = "identical. untouched."
    CREATED = "CREATED."
    OVERWRITTEN = "OVERWRITTEN."
    EXISTING = "existing. SKIPPED."
    FAILED = "FAILED."


def open_(
    filepath: Union[Path, str],
    existing: Union[Existing, str] = Existing.KEEP_TIMESTAMP,
    mkdir: bool = False,
    diffout=None,
    **kwargs,
):
    """
    Return an output file handle, whose timestamp is only updated on content change.

    By default, the filesystem timestamp of a written file is always
    updated on write, also when the final file content is identical to the
    overwritten version. The :any:`OutputFile` class works around this rule.

    The :any:`OutputFile` class behaves like a normal file in write ('w') mode,
    but the output is written to a temporary file. On :any:`close()` the temporary
    file and the target file are compared. If both files are identical, the
    temporary file is removed. If they differ, the temporary file is moved
    to the target file location.

    Args:
        filepath (str): Path to the target file.

    Keyword Args:
        existing (Existing, str): Handling of existing output files:

            * :any:`Existing.ERROR`: raise an ``FileExistsError``open` if the file exists already.
            * :any:`Existing.KEEP`: continue, without modifying the existing file.
            * :any:`Existing.OVERWRITE`: always overwrite the output file, like python's
              :any:`open` would do.
            * :any:`Existing.KEEP_TIMESTAMP`: write to temporary file and move to target
              file if content differs.

        mkdir (bool): create the output directory if it not exists.
        diffout: function receiving file diff on update.

    Raises:
        FileExistsError: if `existing="error"` and file exists already.

    Any keyword argument is simply bypassed to the "open" function,
    except "mode", which is forced to "w".
    """
    return OutputFile(filepath, existing=existing, mkdir=mkdir, diffout=diffout, kwargs=kwargs)


class OutputFile:
    """File Object Wrapper."""

    # pylint: disable=too-many-arguments,too-many-instance-attributes

    def __init__(
        self,
        filepath: Union[Path, str],
        existing: Union[Existing, str] = Existing.KEEP_TIMESTAMP,
        mkdir: bool = False,
        diffout=None,
        kwargs=None,
    ) -> None:
        """File object returned by :any:`open_`."""
        super().__init__()
        if isinstance(filepath, str):
            filepath = Path(filepath)
        if isinstance(existing, str):
            existing = Existing(existing)
        self.filepath = filepath
        self.existing = existing
        self.mkdir = mkdir
        self.diffout = diffout
        self.__handle = None
        self.__open_state = False
        self.__state = None
        self.__file_exists = filepath.exists()
        self.__tmp_filepath = None
        self.__open(kwargs or {})

    @property
    def state(self):
        """State."""
        return self.__state

    def write(self, *args, **kwargs):
        """
        Write to file.

        See :py:meth:`io.TextIOBase.write` for reference.

        Returns:
            None
        Raises:
            ValueError: when the file is already closed.

        """
        if self.__handle:
            self.__handle.write(*args, **kwargs)
        elif not self.__open_state:
            raise ValueError("I/O Error. Write on closed file.")

    def close(self):
        """Close the file."""
        self.__close()

    def flush(self):
        """Flush file content."""
        if self.__handle:
            self.__handle.flush()

    @property
    def closed(self):
        """True, when the file has been closed and is not writable anymore."""
        return not self.__open_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.__state = State.FAILED
        self.__close()

    def __open(self, opts):
        opts.setdefault("encoding", "utf-8")
        filepath = self.filepath
        existing = self.existing
        # Do not overwrite
        if self.__file_exists and existing == Existing.ERROR:
            raise FileExistsError(filepath)
        # Parent Directory
        filedir = filepath.parent
        if not filedir.exists():
            if self.mkdir:
                filedir.mkdir(parents=True, exist_ok=True)
            else:
                raise FileNotFoundError(f"Output directory '{filedir!s}' does not exists.")
        # open
        if existing == Existing.KEEP_TIMESTAMP:
            file, tmp_filepath = tempfile.mkstemp()
            self.__tmp_filepath = Path(tmp_filepath)
            self.__handle = _fdopen(file, "w", **opts)
        elif not self.__file_exists or existing != Existing.KEEP:
            # pylint: disable=consider-using-with,unspecified-encoding
            self.__handle = open(filepath, "w", **opts)
        self.__open_state = True
        self.__state = State.OPEN

    def __close(self):
        # pylint: disable=too-many-branches
        if self.__open_state:
            diff = None
            if self.existing == Existing.KEEP_TIMESTAMP:
                self.__handle.flush()
                self.__handle.close()
                if self.__state != State.FAILED:
                    is_modified = _is_modified(self.filepath, self.__tmp_filepath)
                    if self.diffout and is_modified is True:
                        diff = _get_diff(self.filepath, self.__tmp_filepath)
                    if is_modified is not False:
                        copyfile(self.__tmp_filepath, self.filepath)
                    self.__state = {
                        True: State.UPDATED,
                        False: State.IDENTICAL,
                        None: State.CREATED,
                    }[is_modified]
                self.__tmp_filepath.unlink()
                self.__tmp_filepath = None
            elif self.__handle:
                self.__handle.flush()
                self.__handle.close()
                if self.__state != State.FAILED:  # pragma: no cover
                    if self.__file_exists:
                        self.__state = State.OVERWRITTEN
                    else:
                        self.__state = State.CREATED
            else:
                self.__state = State.EXISTING
            if self.diffout and diff:
                self.diffout(diff)
        self.__handle = None
        self.__open_state = False


def _is_modified(path0, path1):
    if not path0.exists() or not path1.exists():
        return None
    return not filecmp.cmp(path0, path1, shallow=False)


def _get_diff(filepath0, filepath1):
    with open(filepath0, encoding="utf-8") as handle0:
        with open(filepath1, encoding="utf-8") as handle1:
            content0 = handle0.readlines()
            content1 = handle1.readlines()
    diff = difflib.unified_diff(content0, content1)
    return "".join(list(diff))
