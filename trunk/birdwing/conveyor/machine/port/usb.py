# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/machine/port/usb.py
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

import serial

import conveyor.log
import conveyor.machine.port

class UsbPort(conveyor.machine.port.Port):
    def __init__(self, vid, pid, iserial):
        usb_port_category = _find_usb_port_category(vid, pid)
        if usb_port_category is None:
            raise conveyor.error.UsbNoCategoryException(vid, pid, iserial)
        machine_name = self.create_machine_name(vid, pid, iserial);
        machine_type = usb_port_category.machine_type
        super(UsbPort, self).__init__(machine_name, machine_type)
        for driver_name in usb_port_category.driver_names:
           self.driver_profiles[driver_name] = None
        #TODO: get real display name from the bot
        self.display_name = UsbPort.create_machine_hash(machine_name)

        self._log = conveyor.log.getlogger(self)
        
    @staticmethod
    def create_machine_name(vid, pid, iserial):
        return {
            "vid": vid,
            "pid": pid,
            "iserial": iserial,
            "port_type": UsbPort.__name__,
        }

    @staticmethod
    def create_address(machine_name):
        return "usb:%s" % UsbPort.create_machine_hash(machine_name)

    @staticmethod
    def create_machine_hash(machine_name):
        """
        Given a machine name, creates a hashable version of the machine name
        """
        return "%04X:%04X:%s" % (machine_name["vid"], machine_name["pid"],
            machine_name["iserial"])
        
    def __str__(self):
        return str(self.machine_name)

    # Do not use the get_serial* methods if you do not know what you are doing
    def get_serial_port_name(self):
        """
        Lookup the OS specific device path for this port
        """
        serial_ports = serial.tools.list_ports.list_ports_by_vid_pid(self.get_vid(), self.get_pid())
        this_port = filter(lambda d: d['iSerial'] == self.get_iserial(), serial_ports)
        if len(this_port) < 1:
            raise Exception('Serial lookup by iSerial failed')
        this_port = this_port[0] # Ignore duplicate iSerials
        port_name = this_port['port'] # OS specific device path
        return port_name

    def get_serial(self):
        """
        Create a serial.Serial connection to this usb port.
        """
        serial_ports = serial.tools.list_ports.list_ports_by_vid_pid(self.get_vid(), self.get_pid())
        this_port = filter(lambda d: d['iSerial'] == self.get_iserial(), serial_ports)
        if len(this_port) < 1:
            raise Exception('Serial lookup by iSerial failed')
        this_port = this_port[0] # Ignore duplicate iSerials
        port_name = this_port['port'] # OS specific device path
        s = serial.Serial(port_name, baudrate=115200, timeout=.2)

        # TODO: Only apply this hack when it is required
        # There is an interaction between the 8U2 firmware and PySerial where
        # PySerial thinks the 8U2 is already running at the specified baud rate and
        # it doesn't actually issue the ioctl calls to set the baud rate. We work
        # around it by setting the baud rate twice, to two different values. This
        # forces PySerial to issue the correct ioctl calls.
        s.baudrate = 9600
        s.baudrate = 115200
        return s


class _UsbPortCategory(object):
    def __init__(self, vid, pid, machine_type, *driver_names):
        self.vid = vid
        self.pid = pid
        self.machine_type = machine_type
        self.driver_names = driver_names


_USB_PORT_CATEGORIES = [
    _UsbPortCategory(0x0403, 0x6001, 'FTDI',         's3g'),
    _UsbPortCategory(0x2341, 0x0010, 'Arduino Mega', 's3g'),
    _UsbPortCategory(0x23C1, 0xD314, 'Replicator',   's3g'),
    _UsbPortCategory(0x23C1, 0xB015, 'Replicator 2', 's3g'),
    _UsbPortCategory(0x23C1, 0xB016, 'Replicator 2', 's3g'),
    _UsbPortCategory(0x23C1, 0xB017, 'Replicator 2X', 's3g'),
    _UsbPortCategory(0x23C1, 0x0002, 'Digitizer', 'digitizer'),
    _UsbPortCategory(0x23C1, 0x0003, 'Digitizer', 'digitizer'),
    _UsbPortCategory(0x23C1, 0x5c42, 'Digitizer', 'digitizer'),
    _UsbPortCategory(0x23C1, 0x0004, 'Tinkerbell', 'birdwing'),
    _UsbPortCategory(0x23C1, 0x0005, 'Platypus',   'birdwing'),
    _UsbPortCategory(0x23C1, 0x0006, 'Moose',      'birdwing'),    
]

def _find_usb_port_category(vid, pid):
    for usb_port_category in _USB_PORT_CATEGORIES:
        if (vid == usb_port_category.vid and pid == usb_port_category.pid):
            return usb_port_category
    return None

def check_usb(vid, pid):
    """
    Return True if this is (potentially) a MakerBot
    """
    return (None is not _find_usb_port_category(vid, pid))
    
def is_usb_printer_device(vid, pid):
    """ Returns true if the device is a makerbot and is a birdwing device"""
    port_category = _find_usb_port_category(vid, pid)
    
    if (port_category is not None):
        return ('birdwing' in port_category.driver_names)
    else:
        return False
    
def get_port_categories():
    return _USB_PORT_CATEGORIES
