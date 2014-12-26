# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/listener.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2012 MakerBot Industries, LLC
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import errno
import logging
import os
import os.path
import socket
import select
import platform

import conveyor.connection
import conveyor.log
import conveyor.stoppable
import conveyor.platform


class Listener(conveyor.stoppable.StoppableInterface):
    def __init__(self):
        conveyor.stoppable.StoppableInterface.__init__(self)
        self._log = conveyor.log.getlogger(self)

    def accept(self):
        raise NotImplementedError

    def cleanup(self):
        raise NotImplementedError

    def __enter__(self):  # for 'with' statement support
        pass

    def __exit__(self, exc_type, exc_value, traceback):  # for 'with' statement support
        self.cleanup()
        return False


class _AbstractSocketListener(Listener):
    def __init__(self, socket):
        """
        @param socket a socket.socket object
        """
        Listener.__init__(self)
        self._stopped = False
        self._socket = socket

    def stop(self):
        self._stopped = True # conditional gaurd unneeded, run() does not sleep

    def run(self):
        self.accept()

    def accept(self):
        while True:
            if self._stopped:
                return None
            else:
                try:
                    # On windows you must use select for non-blocking.
                    # Otherwise KeyboardInterrupts will be blocked and
                    # conveyor won't be able to exit until a client connects.
                    if conveyor.platform.is_windows():
                        readable, writable, exceptionable = select.select(
                            [self._socket], [], [self._socket], 1)
                    else:
                        readable, writable, exceptionable = select.select(
                            [self._socket], [], [self._socket])
                        
                    if exceptionable:
                        # There's probably a better way to handle this?
                        self._log.info(
                            'Something exceptional happened to a socket.')
                        return None
                    elif readable:
                        sock, addr = self._socket.accept()
                        if platform.system() is "Windows":
                            sock.settimeout(1)
                        self._log_connection(addr)
                        connection = conveyor.connection.SocketConnection(sock, addr)
                        return connection
                except socket.timeout:
                    # NOTE: too spammy
                    # self._log.debug('handled exception', exc_info=True)
                    continue


    def _log_connection(self, addr):
        self._log.info("Accepted %r listener", addr)


class TcpListener(_AbstractSocketListener):
    def cleanup(self):
        pass


class PipeListener(_AbstractSocketListener):
    def __init__(self, path, socket):
        _AbstractSocketListener.__init__(self, socket)
        self._path = path

    def cleanup(self):
        if os.path.exists(self._path):
            os.unlink(self._path)
