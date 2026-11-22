"""Atomic no-overwrite installation inside an already verified directory FD."""

import ctypes
import os
import sys
from .errors import UserError


def install_exclusive_at(directory_fd, source_name, destination_name):
    for name in (source_name, destination_name):
        if not isinstance(name, str) or name in {'', '.', '..'} or '/' in name or '\\' in name or '\x00' in name:
            raise UserError('Exclusive installation requires plain filenames')
    if sys.platform == 'darwin':
        rename = getattr(ctypes.CDLL(None, use_errno=True), 'renameatx_np', None)
        if rename is None:
            raise UserError('This volume does not support safe exclusive installation')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(directory_fd, os.fsencode(source_name), directory_fd, os.fsencode(destination_name), 0x4):
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
    else:
        os.link(source_name, destination_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        os.unlink(source_name, dir_fd=directory_fd)
