# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/server/__main__.py
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
# import os
# import sys
# this_script_path = os.path.dirname(os.path.abspath(__file__))
# up = os.path.abspath(os.path.join(this_script_path, '../../'))
# sys.path.append(up)
# up = os.path.abspath(os.path.join(this_script_path, '../../../'))
# sys.path.append(up)
# #sys.path.append('/root/alexey/printer/makerbot_5th/python/lockfile-0.9.1-py2.7.egg')
# # setting eggs
# # import imp
# # this_script_path = os.path.dirname(os.path.abspath(__file__))
# # up = os.path.abspath(os.path.join(this_script_path, '../../'))
# # load = imp.load_source('conveyor_path', os.path.join(up, 'conveyor_path.py'))
#

import lockfile.pidlockfile
import logging
import os
import signal
import sys

import conveyor
import conveyor.arg
import conveyor.log
import conveyor.main
import conveyor.machine
import conveyor.machine.port
import conveyor.server

from conveyor.decorator import args

# Done to be able to gain a reference to the server instance from outside the interpreter.
# Required for device notifications from native application embedding the interpreter.
server = object()

@args(conveyor.arg.nofork)
class ServerMain(conveyor.main.AbstractMain):
    _program_name = 'conveyord'

    _config_section = 'server'

    _logging_handlers = ['log',]

    def _run(self):
        self._log_startup(logging.INFO)
        self._init_event_threads()
        driver_manager = conveyor.machine.DriverManager.create(self._config)
        address = self._config.get('common', 'address')
        listener = address.listen()
        embedded_address = self._config.get('common', 'embedded_address')
        with listener:
            self._log.info('Listening for client connections')
            global server
            server = conveyor.server.Server(
                self._config, driver_manager, listener,
                embedded_address)
            # Hotplugging only starts after we assign to server...
            if self._config.get('server', 'usb_supported'):
                server.usb_scan_devices()
            code = server.run()
            return code

def _main(argv): # pragma: no cover
    conveyor.log.earlylogging('conveyord')
    main = ServerMain()
    code = main.main(argv)
    if None is code:
        code = 0
    return code

if '__main__' == __name__: # pragma: no cover
#     this_script_path = os.path.dirname(os.path.abspath(__file__))
#     up = os.path.abspath(os.path.join(this_script_path, '../../'))
#     sys.path.append(up)
    sys.exit(_main(sys.argv))
