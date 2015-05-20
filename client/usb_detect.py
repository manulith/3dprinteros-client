#!/usr/bin/env python
# -*- coding: utf-8 -*-

#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

# Author: Vladimir Avdeev <another.vic@yandex.ru> 2015

import re
import string
import logging
import usb.core
import usb.util
import usb.backend.libusb1
import serial.tools.list_ports

import paths
import config

class USBDetector:
    vid_pid_re = re.compile(
        '(?:.*\=([0-9-A-Z-a-f]+):([0-9-A-Z-a-f]+))|(?:.*VID_([0-9-A-Z-a-f]+)\+PID_([0-9-A-Z-a-f]+)\+)')
    serial_number_re = re.compile('.*SNR\=([0-9-A-Z-a-f]+).*')


    @classmethod
    def format_vid_or_pid(cls, vid_or_pid):
        return hex(vid_or_pid)[2:].zfill(4).upper()

    def __init__(self):
        self.unused_serial_ports = []
        self.printers = []

    def detect_devices(self):
        logger = logging.getLogger('app.' + __name__)
        try:
            devices = usb.core.find(find_all=True)
            devices = list(devices)
            if not devices:
                raise ValueError
        except ValueError:
            backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=paths.get_libusb_path)
            devices = usb.core.find(find_all=True, backend=backend_from_our_directory)
        if not devices:
            logger.warning("Libusb error: no usb devices was detected. Check if libusb1 is installed.")
        self.all_devices = list(devices)

    def detect_serial_ports(self):
        serial_ports = list(serial.tools.list_ports.comports())
        self.all_serial_ports = serial_ports
        self.unused_serial_ports = filter(lambda x: x[2] != "n/a", serial_ports)


    def get_printers_list(self):
        self.detect_devices()
        self.detect_serial_ports()
        printers_info = []
        for dev in self.all_devices:
            dev_info = {
                'VID': USBDetector.format_vid_or_pid(dev.idVendor), #cuts "0x", fill with zeroes if needed, doing case up
                'PID': USBDetector.format_vid_or_pid(dev.idProduct),
            }
            try:
                SNR = str(usb.util.get_string(dev, dev.iSerialNumber))
            except:
                SNR = None
            else:
                if SNR:
                    for symbol in SNR:
                        if not symbol in string.printable:
                            SNR = None
                            break
            dev_info['SNR'] = SNR
            # try:
            # manufacturer = dev.manufacturer  # can provoke crash of libusb
            #     device_dct['Manufacturer'] = manufacturer
            # except (usb.core.USBError, AttributeError, NotImplementedError):
            #     pass
            # try:
            #     product = dev.product  # can provoke                 can provoke crash of libusb
            #     device_dct['Product'] = product
            # except (usb.core.USBError, AttributeError, NotImplementedError):
            #     pass
            if self.device_is_printer(dev_info):
                if SNR:
                    dev_info['COM'] = self.get_serial_port_name(dev_info['VID'], dev_info['PID'], SNR)
                else:
                    dev_info['COM'] = None
                printers_info.append(dev_info)
            #dev.close()
            #logger.debug(device_dct)
        for printer_info in printers_info:
            if not printer_info['SNR']:
                serial_port_name = self.get_serial_port_name(printer_info['VID'], printer_info['PID'], None)                
                serial_number = self.get_snr_by_serial_port_name(serial_port_name)                
                printer_info['COM'] = serial_port_name
                printer_info['SNR'] = serial_number
        self.all_devices = []
        return printers_info

    def get_snr_by_serial_port_name(self, serial_port_name):        
        for port_dct in self.all_serial_ports:            
            if port_dct[0] == serial_port_name:
                vid_pid_snr_string = port_dct[2]
                match = self.serial_number_re.match(vid_pid_snr_string)
                if match:
                    return match.group(1)

    def get_serial_port_name(self, vid, pid, snr):
        for port_dct in self.unused_serial_ports:
            match = self.vid_pid_re.match(port_dct[2])
            if match:
                vid_of_comport = match.group(1)
                pid_of_comport = match.group(2)
                if not vid_of_comport or not pid_of_comport:
                    vid_of_comport = match.group(3)
                    pid_of_comport = match.group(4)
                vid_of_comport = vid_of_comport.zfill(4).upper()
                pid_of_comport = pid_of_comport.zfill(4).upper()
                if vid == vid_of_comport and pid == pid_of_comport:
                    if snr and not 'SNR=' + snr.upper() in port_dct[2].upper():
                        continue
                    self.unused_serial_ports.remove(port_dct)
                    return port_dct[0]
        return None

    def device_is_printer(self, device):
        profiles = config.get_profiles()
        if not profiles: return True #for debug purposes
        for profile in profiles:
            if [ device['VID'], device['PID'] ] in profile[ u"vids_pids" ]:
                return True

if __name__ == '__main__':
    detector = USBDetector()
    printers = detector.get_printers_list()
    print "\nAll devices:"
    for printer in printers:
        print printer
    printers = filter(lambda x: x['COM'], printers)
    print "\nDevices with serial port:"
    for printer in printers:
        print printer