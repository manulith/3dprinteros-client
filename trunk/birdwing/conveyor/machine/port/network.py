# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/machine/port/__init__.py
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

import conveyor.machine.port

class NetworkPort(conveyor.machine.port.Port):
    """
    Contains information about a discovered etherenet port.

    @params dict indata: table of data about this port.
    """

    def __init__(self, indata):
        print("Creating machine port from: " + str(indata))
        machine_name = self.create_machine_name(indata['ip'], indata['port'],
            indata['vid'], indata['pid'], indata['iserial'])
        machine_type = indata["machine_type"]
        super(NetworkPort, self).__init__(machine_name, machine_type)
        self.display_name = indata["machine_name"]
        self.driver_profiles["birdwing"] = [machine_type.title()]
        self.profile_name = machine_type.title()
        self._data = indata

    def get_info(self):
        info = super(NetworkPort, self).get_info()
        info["display_name"] = self.display_name
        return info

    @staticmethod
    def create_machine_name(ip, port, vid, pid, iserial):
        return {
            "ip": ip,
            "port": port,
            "vid": vid,
            "pid": pid,
            "iserial": iserial,
            "port_type": NetworkPort.__name__,
        }

    @staticmethod
    def create_address(machine_name):
        return "tcp:%s" % NetworkPort.create_machine_hash(machine_name)

    @staticmethod
    def create_machine_hash(machine_name):
        return "%s:%s" % (machine_name["ip"], machine_name["port"])

    def __str__(self):
        mach_model = self.machine_type
        return "%s, %s" % (self.machine_name, mach_model)
