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

import conveyor.address

class Port(object):
    """
    Superclass for port objects.
    """
    def __init__(self, machine_name, machine_type):
        self.driver_profiles = {}
        self.machine_name = machine_name
        self.machine_type = machine_type
        # Since the name may not be hashable, we have a separate hash value
        self.machine_hash = self.create_machine_hash(machine_name)
        self.port_type = self.__class__.__name__
        self.machine = None
        self.address = conveyor.address.Address.address_factory(
            self.create_address(self.machine_name))
        self.disconnected_callbacks = []

    def register_disconnected_callbacks(self, machine):
        machine._disconnected_callbacks.extend(self.disconnected_callbacks[:])

    def get_info(self):
        return { 
            "driver_profiles": self.driver_profiles,
            "machine_name": self.machine_name,
            "machine_type": self.machine_type,
            "machine_hash": self.machine_hash,
            "port_type": self.port_type,
        }

    def get_vid(self):
        return self.machine_name["vid"]

    def get_pid(self):
        return self.machine_name["pid"]

    def get_iserial(self):
        return self.machine_name["iserial"]

    def get_machine_hash(self):
        return self.machine_hash

    @staticmethod
    def create_machine_name():
        raise NotImplementedError

    @staticmethod
    def create_machine_hash(machine_name):
        """
        We would like to support naming a machine a non-hashable value, so we
        support this machine_hash value.
        """
        raise NotImplementedError

    @staticmethod
    def create_address(machine_name):
        raise NotImplementedError
