# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/connection.py
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
import select
import socket
import threading
import time
import usb.core
import platform

import conveyor.log
import conveyor.stoppable


class Connection(conveyor.stoppable.StoppableInterface):
    """ Base class for all conveyor connection objects """

    def __init__(self):
        conveyor.stoppable.StoppableInterface.__init__(self)
        self._log = conveyor.log.getlogger(self)

    def read(self):
        """
        This method MUST raise an EOFError when encountering an EOF, and
        MAY return '' to indicate that there is no data available yet.
        """
        raise NotImplementedError

    def write(self, data):
        "Template write function, not implemented."
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

# Definitions for USB class IDs
USB_COMPOSITE_CLASS = 0
USB_PRINTER_CLASS_ID = 7

class UsbConnectionFactory:
    """ A factory that actually is a factory.  Returns a USB class-specific connection object """
    """ based on the class id of the provided device. """
    @staticmethod
    def create(device):
        class_dict = {}
        if device.bDeviceClass == USB_COMPOSITE_CLASS:
            for configuration in device:
                for interface in configuration:
                    if interface.bInterfaceClass not in class_dict:
                        class_dict[interface.bInterfaceClass] = {
                            'configuration' : configuration.bConfigurationValue,
                            'interface' : (interface.bInterfaceNumber,
                                           interface.bAlternateSetting)}
        else:
            # If we are not a composite class, we just use the default configuration
            # and interface.  pyusb uses 'None' to denote the default configuration,
            # and (0,0) should be the default interface.
            class_dict[device.bDeviceClass] = {'configuration' : None, 'interface' : (0,0)}

        # List all supported classes with preferred classes first
        if USB_PRINTER_CLASS_ID in class_dict:
            return UsbPrinterConnection(device, class_dict[USB_PRINTER_CLASS_ID])

        raise UsbClassNotSupportedException(class_dict.keys())

class UsbPrinterConnection(Connection):
    """Encapsulates a connection to a connected USB printer class device"""

    def __init__(self, device, device_dict):
        """
        @param device The USB device object to be used in the connection
        """
        Connection.__init__(self)
        self._write_condition = threading.Condition()
        self._read_condition = threading.Condition()
        self._stopped = False
        self._device = device
        self._check_kernel_driver()
        self._device.set_configuration(device_dict['configuration'])
        self._configuration = self._device.get_active_configuration()
        self._interface = self._configuration[device_dict['interface']]
        # TODO: Should we assume that the IN interface is listed first?
        self._bulkInEp = self._interface[0]
        self._bulkOutEp = self._interface[1]

    def _check_kernel_driver(self):
        """ Make sure that there is no kernel driver attached to the device
            For now we detach any kernel drivers found, but it would be
            better to prevent them from attaching with udev.
        """
        try:
            configuration = self._device.get_active_configuration()
            for interface in configuration:
                if self._device.is_kernel_driver_active(interface.bInterfaceNumber):
                    self._device.detach_kernel_driver(interface.bInterfaceNumber)
        except:
            # We expect this to fail on windows, and if it fails elsewhere, maybe the
            # kernel driver will still work
            pass

    def stop(self):
        self._stopped = True
        self._device.stop()

    def read(self):
        # timeout=0 ensures a blocking read that will never time out
        try:
            with self._read_condition:
                # Check stopped here so that we never attempt to
                # read a device after we close it
                if self._stopped: raise EOFError()
                data = self._bulkInEp.read(4096, timeout=0).tostring()
        except usb.core.USBError as e:
            self._log.info('USB Read Error for VID: %d, PID: %d - %s'
                % (self._device.idVendor, self._device.idProduct, str(e)))
            self.close()
            raise EOFError()
        return data

    def write(self, data):
        #self._log.info('Send:'+repr(data))
        cap = 8192 # This may be a limit for g_3dprinter.ko
        with self._write_condition:
            totalSent = 0
            while not self._stopped and totalSent < len(data):
                try:
                    unsent_data = data[totalSent:]
                    if len(unsent_data) > cap:
                        numSent = self._bulkOutEp.write(unsent_data[0:cap], timeout=0)
                    else:
                        numSent = self._bulkOutEp.write(unsent_data, timeout=0)
                except usb.core.USBError as e:
                    self._log.debug('USB Write Error for VID: %d, PID: %d, iSerial: %d, Class %d - %s'
                                    % (self._device.idVendor, self._device.idProduct,
                                       self._device.iSerialNumber, self._device.bDeviceClass, str(e)))
                    continue
                else:
                    totalSent += numSent
        return

    def close(self):
        self.stop()
        with self._read_condition, self._write_condition:
            # Don't close the device while reads/writes are in progress
            self._device.close()

class ConnectionWriteException(Exception):
    """ Default connection exception class."""
    pass

class SocketConnection(Connection):
    """
    Connection wrapper that sits on top of a python socket to handle errors and
    longer reads/writes more gracefully.
    """

    def __init__(self, socket, address):
        """
        @param socket a socket object
        @param address
        """
        Connection.__init__(self)
        self._condition = threading.Condition()
        self._stopped = False
        self._socket = socket
        self._address = address

    def getaddress(self):
        return self._address

    def stop(self):
        """
        Sets the stop flag to True and closes the socket.
        "We don't need to grab a mutex here, since boolean operations are atomic"
            ~ Matthew William Samsonoff

        Calling this function while a socket is reading could potentially cause
        EBADF (Bad File Descriptor) errors
        """
        self._stopped = True
        try:
            self._socket.shutdown(socket.SHUT_RD)
            self._socket.close()
        except IOError as e:
            self._log.debug('handled exception', exc_info=True)


    def write(self, data):
        """
        writes data over a socket. Loops until either .stop() is set or
        data has been sent successfully. Exceptions for flow are handled in
        this functions, others are throw upwards.

        @param data The data you want to send
        """
        with self._condition:
            i = 0
            while not self._stopped and i < len(data):
                try:
                    sent = self._socket.send(data[i:])
                except IOError as e:
                    if e.args[0] in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                        # NOTE: debug too spammy
                        # self._log.debug('handled exception', exc_info=True)
                        continue
                    elif e.args[0] in (errno.EBADF, errno.EPIPE):
                        self._log.debug('handled exception', exc_info=True)
                        if self._stopped:
                            break
                        else:
                            raise ConnectionWriteException
                    else:
                        raise
                else:
                    i += sent

    def read(self):
        while True:
            if self._stopped:
                return ''
            else:
                try:
                    # One second timeout is arbitrary, but should be short.
                    # This sets the maximum amount of time it can take a
                    # machine thread to shut down.  On windows the total time
                    # for shutdown must be < 30 seconds, or the os will
                    # force-kill us (a common-around-the-office case is a dozen
                    # or more bots on the network.
                    readable, writable, exceptionable = select.select(
                        [self._socket], [], [self._socket], 1)
                        
                    if exceptionable:
                        # There's probably a better way to handle this?
                        self._log.info(
                            'Something exceptional happened to a socket.')
                        raise EOFError()
                    elif readable:
                        data = self._socket.recv(4096)
                        if data == '':
                            raise EOFError()
                        return data
                    else:
                        return ''
                except IOError as e:
                    if e.args[0] in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                        # NOTE: too spammy
                        # self._log.debug('handled exception', exc_info=True)
                        continue
                    elif errno.ECONNRESET == e.args[0]:
                        self._log.debug('handled exception', exc_info=True)
                        raise EOFError()
                    else:
                        raise


    def close(self):
        self._socket.close()

class UsbClassNotSupportedException(Exception):
    """ Thrown when we attempt to construct a connection to a USB device class that """
    """ is not supported. """
    def __init__(self, classid):
        Exception.__init__(self, classid)
        self.classid = classid
