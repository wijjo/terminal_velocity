"""Persistent note storage and search.

This module defines the NoteBook and Note interfaces and provides
PlainTextNoteBook and PlainTextNote implementations that store notes in a
directory of plain text files.

Other implementations could store notes differently (e.g. in a database) and
provide drop-in replacements for PlainTextNoteBook and PlainTextNote by
implementing the same NoteBook and Note interfaces.

TODO: Extract the NoteBook and Note interfaces into separate interface classes
for clarity.

A NoteBook is a container of Notes. It behaves like a standard Python
container, e.g. you can do:

    notebook = PlainTextNoteBook("/path/to/my/notes/dir")

    note = notebook[5]

    for note in notebook:
        ...

    if note in notebook:
        ...

    len(notebook)

    reversed(notebook)

    del notebook[3]

    notebook.remove(note)

When deleting or removing a Note from a NoteBook, DelNoteError may be raised if
removing the note fails.

You should not initialise your own Note objects when working with a NoteBook,
instead use the NoteBook's add_new() method:

    try:
        note = notebook.add_new("The Title of My New Note")
    except AddNoteError:
        ...

NoteBooks also provide a search() method for doing fast, full-text search of
notes:

    matching_notes = notebook.search(query)

This module provides a simple brute force full text search implementation.
Other modules could provide better search functions that could be plugged in.

"""

import os
import sys
import logging
import chardet  #pylint: disable=E0401

LOGGER = logging.getLogger(__name__)    #pylint: disable=C0103

def unicode_or_bust(raw_text):
    """Return the given raw text data decoded to unicode.

    If the text cannot be decoded, return None.

    """
    encodings = ["utf-8"]
    for encoding in (sys.getfilesystemencoding(), sys.getdefaultencoding()):
        # I would use a set for this, but they don't maintain order.
        if encoding not in encodings:
            encodings.append(encoding)

    for encoding in encodings:
        if encoding:  # getfilesystemencoding() may return None
            try:
                decoded = raw_text.decode(encoding=encoding)
                return decoded
            except UnicodeDecodeError:
                pass

    # If none of those guesses worked, let chardet have a go.
    encoding = chardet.detect(raw_text)["encoding"]
    if encoding and encoding not in encodings:
        try:
            decoded = raw_text.decode(encoding=encoding)
            LOGGER.debug("File decoded with chardet, encoding was %s", encoding)
            return decoded
        except UnicodeDecodeError:
            pass
        except LookupError:
            pass

    # I've heard that decoding with cp1252 never fails, so try that last.
    try:
        decoded = raw_text.decode(encoding="cp1252")
        LOGGER.debug("File decoded with encoding cp1252")
        return decoded
    except UnicodeDecodeError:
        pass

    # If nothing worked then give up.
    return None


class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class NewNoteBookError(Error):
    """Exception raised if initialising a new NoteBook fails.

    """
    def __init__(self, value):
        self.value = value
        Error.__init__("Error while creating a new notebook.")

    def __str__(self):
        return repr(self.value)


class NewNoteError(Error):
    """Exception raised if making a new Note or adding it to a NoteBook fails.

    """
    def __init__(self, value):
        self.value = value
        Error.__init__("Error while creating a new note.")

    def __str__(self):
        return repr(self.value)


class NoteAlreadyExistsError(NewNoteError):
    """Exception raised when trying to add a new note that already exists.

    """
    pass


class InvalidNoteTitleError(NewNoteError):
    """Exception raised when trying to add a new note with an invalid title.

    """
    pass


class DelNoteError(Error):
    """Exception raised if removing a Note from a NoteBook fails.

    """
    def __init__(self, value):
        self.value = value
        Error.__init__("Error while deleting a note.")

    def __str__(self):
        return repr(self.value)


class PlainTextNote(object):
    """A note, stored as a plain text file on disk."""

    def __init__(self, title, notebook, extension):
        """Initialise a new PlainTextNote.

        A path for the note's file will be generated from the NoteBook's
        path and the given title and extension.

        If a file already exists at the given path, it will be used as the
        note's file. If not, an empty file will be created (parent directories
        will be created also, if necessary).

        The modified time of the note will be read from the mtime of the file.

        Raises NewNoteError if something goes wrong when creating or reading
        the note file.

        Keyword arguments:
        title -- the title for the note
        notebook -- the PlainTextNoteBook this PlainTextNote will belong to
        extension -- the filename extension to use (string, should start with
            a dot e.g. ".txt")

        """
        self._title = title
        self._notebook = notebook
        self._extension = extension
        self._filename = self.title + self._extension
        self._abspath = os.path.join(self._notebook.path, self._filename)

        # Create the file's parent directories (including note directory
        # subdirs) if they don't exist.
        directory = os.path.split(self.abspath)[0]
        if not os.path.isdir(directory):
            LOGGER.debug("%s doesn't exist, creating it", directory)
            try:
                os.makedirs(directory)
            except os.error as exc:
                raise NewNoteError(
                    "{0} could not be created: {1}".format(directory, exc))

        # Create an empty file if the file doesn't exist.
        open(self.abspath, 'a')

    @property
    def title(self):
        """'title' property"""
        return self._title

    @title.setter
    def set_title(self, new_title):
        # TODO: Implement note renaming. Should rename file on disk.
        raise NotImplementedError

    @property
    def extension(self):
        """'extension' property"""
        return self._extension

    @property
    def contents(self):
        """'contents' property"""
        contents = unicode_or_bust(open(self.abspath, "rb").read())
        if contents is None:
            LOGGER.error(
                "Could not decode file contents: %s", self.abspath)
            return ""
        return contents

    @property
    def mtime(self):
        """'mtime' property"""
        return os.path.getmtime(self.abspath)

    @property
    def abspath(self):
        """'abspath' property"""
        return self._abspath

    def __eq__(self, other):
        return getattr(other, 'abspath', None) == self.abspath


def brute_force_search(notebook, query):
    """Return all notes in `notebook` that match `query`.

    Returns a sequence of Note objects that match the given search query.

    Arguments:

    notebook - the notebook to search (NoteBook)

    query - the query to search for (string)

    This is implemented as a standalone function so it can easily be replaced
    with some other function that does the search differently (e.g. you could
    have a config option to choose between different search implementations).

    This implementation does a brute force search that simply reads every file
    in the notebook looking for the search words.

    """
    search_words = query.strip().split()
    matching_notes = []
    for note in notebook:
        match = True
        for search_word in search_words:
            if search_word.islower():
                # Search for word case-insensitively.
                in_title = search_word in note.title.lower()
                in_contents = search_word in note.contents.lower()
            else:
                # Search for word case-sensitively.
                in_title = search_word in note.title
                in_contents = search_word in note.contents
            if (not in_title) and (not in_contents):
                match = False
        if match:
            matching_notes.append(note)
    return matching_notes


class PlainTextNoteBook(object):
    """A NoteBook that stores its notes as a directory of plain text files."""

    #pylint: disable=R0913,R0912,R0914
    def __init__(self, path, extension, extensions,
                 search_function=brute_force_search, exclude=None):
        """Make a new PlainTextNoteBook for the given path.

        If `path` does not exist it will be created (parent directories too).

        If `path` does exist, any note files in path will be read and included
        in the NoteBook. Subdirectories in `path` will be read recursively.

        Raises NewNoteBookError if creating the notebook directory or reading
        the files in an existing directory fails.

        Arguments:

        path -- absolute path to the directory where this NoteBook's note files
            are kept (string)

        extension -- the filename extension to use for new notes (string)

        extensions -- the filename extensions to read in the notes dir
            (list of strings)

        search_function -- the function to call to search the notebook

        """
        # Expand ~ in path, and transform it into an absolute path.
        self._path = os.path.abspath(os.path.expanduser(path))

        if extension and not extension.startswith("."):
            extension = "." + extension
        self.extension = extension
        self.search_function = search_function
        self.exclude = exclude
        if not self.exclude:
            self.exclude = []

        self.extensions = []
        for dot_extension in extensions:
            if not dot_extension.startswith("."):
                dot_extension = "." + dot_extension
            self.extensions.append(dot_extension)

        # Create notebook_dir if it doesn't exist.
        if not os.path.isdir(self.path):
            LOGGER.debug("%s doesn't exist, creating it", self.path)
            try:
                os.makedirs(self.path)
            except os.error as exc:
                raise NewNoteBookError(
                    "{0} could not be created: {1}".format(self.path, exc))
        else:
            # TODO: Check that self.path is a directory, if not raise.
            pass

        # Read any existing note files in the notes directory.
        self._notes = []
        for root, dirs, files in os.walk(self.path):

            # ignore any dirs we don't want to check
            for name in self.exclude:
                if name in dirs:
                    dirs.remove(name)

            for filename in files:

                # ignore anything listed in our 'exclude' list
                if filename in self.exclude:
                    continue

                # Ignore hidden and backup files.
                if filename.startswith('.') or filename.endswith('~'):
                    continue

                if os.path.splitext(filename)[1] not in self.extensions:
                    continue

                # Make a Note object for the file and add it to this NoteBook.
                abspath = os.path.join(root, filename)
                relpath = os.path.relpath(abspath, self.path)
                relpath, ext = os.path.splitext(relpath)
                self.add_new(title=relpath, extension=ext)

    @property
    def path(self):
        """'path' property"""
        return self._path

    def search(self, query):
        """Return a sequence of Notes that match the given query.

        Arguments:
        query -- the search query match notes against (string)

        """
        return self.search_function(self, query)

    def add_new(self, title, extension=None):
        """Create a new Note and add it to this NoteBook.

        Returns the newly-created Note object.

        Raises NewNoteError if creating or adding the Note fails.

        Raises NoteAlreadyExistsError if creating or adding the Note fails
        because this NoteBook already contains a Note with the given title.

        Notes can be added to subdirectories of the notebook directory by
        putting slashes in their titles, e.g.
        "programming/python/How to use Decorators in Python"

        Arguments:
        title -- the title for the new note (string)
        extension -- the filename extension for the new note (string, should
            start with a dot e.g. ".txt")

        """
        if extension is None:
            extension = self.extension

        # Don't create notes outside of the notes dir.
        if title.startswith(os.sep):
            title = title[len(os.sep):]

        title = title.strip()

        if not os.path.split(title)[1]:
            # Don't create notes with empty filenames.
            raise InvalidNoteTitleError(
                "Invalid note title: {0}".format(title))

        # Check that we don't already have a note with the same title and
        # extension.
        for note in self._notes:
            if note.title == title and note.extension == extension:
                raise NoteAlreadyExistsError(
                    "Note already in NoteBook: {0}".format(note.title))

        # Ok, add the note.
        note = PlainTextNote(title, self, extension)
        self._notes.append(note)
        return note

    def __len__(self):
        return len(self._notes)

    def __getitem__(self, index):
        return self._notes[index]

    def __delitem__(self, index):
        raise NotImplementedError

    def __iter__(self):
        return self._notes.__iter__()

    def __reversed__(self):
        return self._notes.__reversed__()

    def __contains__(self, note):
        return note in self._notes
