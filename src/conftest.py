"""Shared pytest setup."""

import os
import tempfile

# The tracking checks reject evidence files below a symlinked directory.
# The default macOS temp directory sits below the /var symlink, so resolve it.
tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
