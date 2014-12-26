# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/address.py
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

import os
import socket

import usb.core
import usb.util

import conveyor.connection
import conveyor.listener


class Address(object):
    """
    Base class for a addressable endpoint. This class can create the
    underlying sockets as needed based on the communication endpoint type.
    """

    @staticmethod
    def address_factory(addr):
        """ Constructs an Address object based on the passed string
        @param s Address string in the form pipe:$NAME or tcp:$URL:$PORT
        @returns A proper Address-based object, based on type address type
        """
        split = addr.split(':',1)
        if 'pipe' == split[0]:
            addressObj = PipeAddress.factory(addr, split)
        elif 'tcp' == split[0]:
            addressObj = TcpAddress.factory(addr, split)
        elif 'usb' == split[0]:
            addressObj = UsbAddress.factory(addr, split)
        else:
            raise UnknownProtocolException(addr, split[0])
        return addressObj


    def listen(self):
        raise NotImplementedError

    def connect(self):
        raise NotImplementedError

    def __str__(self):
        raise NotImplementedError


class PipeAddress(Address):
    @staticmethod
    def factory(s, split):
        protocol = split[0]
        if 'pipe' != protocol:
            raise UnknownProtocolException(protocol,'pipe')
        if 2 != len(split):
            raise MissingPathException(s)
        path = split[1]
        if 0 == len(path):
            raise MissingPathException(s)
        address = PipeAddress(path)
        return address

    def __init__(self, path):
        self._path = path

    def __str__(self):
        s = ':'.join(('pipe', self._path))
        return s

    def listen(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.setblocking(True)
        try:
            s.bind(self._path)
        except IOError:
            # Path to socket already exists, so lets try to connect
            try:
                s.connect(self._path)
                # Connected, so conveyor is already running
                s.close()
                raise ConveyorAlreadyRunningException(self._path)
            except IOError:
                # Could not connect, so conveyor must have crashed
                print("Could not connect, so conveyor must have crashed")
                os.remove(self._path)
                s.bind(self._path)
        os.chmod(self._path, 0666)
        s.listen(socket.SOMAXCONN)
        listener = conveyor.listener.PipeListener(self._path, s)
        return listener

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.setblocking(True)
        s.connect(self._path)
        connection = conveyor.connection.SocketConnection(s, None)
        return connection

class TcpAddress(Address):
    @staticmethod
    def factory(s, split):
        protocol = split[0]
        if 'tcp' != protocol:
            raise UnknownProtocolException(protocol, 'tcp')
        if 2 != len(split):
            raise MissingHostException(s)
        hostport = split[1].split(':', 1)
        if 2 != len(hostport):
            raise MalformedUrlException(s)
        host = hostport[0]
        if 0 == len(host):
            raise MissingHostException(s)
        try:
            port = int(hostport[1])
        except ValueError:
            raise InvalidPortException(s, hostport[1])
        address = TcpAddress(host, port)
        return address

    def __init__(self, host, port):
        """
        @param host: name of computer we are connecting to
        @param port: number-id of port we are connecting to
        """
        self._host = host
        self._port = port
        self._log = conveyor.log.getlogger(self)

    def listen(self):
        """ creates a listener object connected to the specified port
        self._host must be a refer to the local host
        self._port must be a valid port
        """
        return self.listener_factory(self._port, self._host)

    @staticmethod
    def listener_factory(port, host='localhost'):
        """
        @param port must be an integer port number
        @param host must be a string reference to localhost
        @return a TcpListener object connected to the specified socket
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(socket.SOMAXCONN)
        listener = conveyor.listener.TcpListener(s)
        return listener

    def create_connection(self):
        # I've noticed some connect calls take a super long time to return.
        # This becomes an issue when we start makerware; makerware will try
        # to connect to all the machines it sees before it begins drawing
        # the GUI, which makes it appear like makerware crashed.
        try:
            timeout = 1
            s = socket.create_connection((self._host, self._port), timeout=timeout)
            s.settimeout(None)
            connection = conveyor.connection.SocketConnection(s, None)
            return connection
        except Exception as ex:
            self._log.info("ERROR: error connecting to %s : %s", self._host, self._port, exc_info=True)
            raise

    def connect(self):
        """ creates a connection based on internal settings.
        @returns a SocketConnection object
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((self._host, self._port))
        connection = conveyor.connection.SocketConnection(s, None)
        return connection

    def __str__(self):
        s = ':'.join(('tcp', self._host, str(self._port)))
        return s

class UsbAddress(Address):
    @staticmethod
    def factory(s, split):
        # connect string will be in the form usb:VID:PID:ISerial
        ids = split[1].split(':')
        if 3 != len(ids):
            raise MalformedUsbAddressException(s)

        try:
            vid = int(ids[0], 16)
            pid = int(ids[1], 16)
            iserial = ids[2]
        except ValueError as e:
            raise InvalidUsbAddressParameterException(str(e))

        address = UsbAddress(vid, pid, iserial)
        return address

    def __init__(self, vid, pid, iserial):
        """
        @param vid: vendor id of the device we are connecting to
        @param pid: product id of the device we are connecting to
        @param iserial: iserial value of the device we are connecting to
        """
        self._log = conveyor.log.getlogger(self)
        self._vid = vid
        self._pid = pid
        self._iserial = iserial
        self._device = None

    def connect(self):
        """ creates a connection based on internal settings.
        @returns a UsbConnection object
        """
        # Find the specified MakerBot printer class device.
        # TODO: find a way to implement this without re-polling the serial
        # number of every machine matching our VID and PID
        for device in usb.core.find(find_all = True, idVendor=self._vid, idProduct=self._pid):
            try:
                iserial = usb.util.get_string(device, device.iSerialNumber)
                if iserial == self._iserial:
                    self._device = device
            except IOError as e:
                self._log.info("Could not open %04X:%04X: %s",
                               self._vid, self._pid, str(e))

        if self._device is None:
            raise UsbDeviceNotFoundException(self._vid, self._pid, self._iserial)

        connection = conveyor.connection.UsbConnectionFactory.create(self._device)
        return connection

    # TODO: remove this when it is removed from _BirdWingClient
    def create_connection(self):
        return self.connect()

    def __str__(self):
        s = "usb:%04X:%04X:%d" % (self._vid, self._pid, self._iserial)
        return s


class UnknownProtocolException(Exception):
    def __init__(self, value, protocol):
        Exception.__init__(self, value, protocol)
        self.value = value
        self.protocol = protocol

class MissingHostException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

class MalformedUrlException(Exception):
    """ Error when a tcp port specificion or url specification is invalid."""
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

class InvalidPortException(Exception):
    def __init__(self, value, port):
        Exception.__init__(self, value, port)
        self.value = value
        self.port = port

class MissingPathException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

class MalformedUsbAddressException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

class InvalidUsbAddressParameterException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

class UsbDeviceNotFoundException(Exception):
    def __init__(self, vid, pid, iserial):
        Exception.__init__(self, vid, pid, iserial)
        self.vid = vid
        self.pid = pid
        self.iserial = iserial

class ConveyorAlreadyRunningException(Exception):
    def __init__(self, value):
        Exception.__init__(self)
        self.value = value
