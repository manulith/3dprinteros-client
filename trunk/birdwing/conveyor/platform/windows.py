# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/platform/windows.py
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

DEFAULT_CONFIG_COMMON_ADDRESS = 'tcp:127.0.0.1:9999'

DEFAULT_CONFIG_EMBEDDED_ADDRESS = 'tcp:10.1.0.106:9999'

DEFAULT_CONFIG_COMMON_PID_FILE = 'conveyord.pid'

DEFAULT_CONFIG_SERVER_LOGGING_FILE = 'conveyord.log'
