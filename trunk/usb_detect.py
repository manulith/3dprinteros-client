#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import string
import logging
import usb.core
import usb.util
import usb.backend.libusb1
import serial.tools.list_ports

import utils
from config import Config

class USBDetector:
    vid_pid_re = re.compile(
        '(?:.*\=([0-9-A-Z-a-f]+):([0-9-A-Z-a-f]+))|(?:.*VID_([0-9-A-Z-a-f]+)\+PID_([0-9-A-Z-a-f]+)\+)')

    @classmethod
    def format_vid_or_pid(vid_or_pid):
        return hex(vid_or_pid)[2:].zfill(4).upper()

    def __init__(self):
        self.all_devices = []
        self.used_serial_ports = []
        self.printers = []

    def get_devices(self):
        logger = logging.getLogger('app.' + __name__)
        try:
            devices = usb.core.find(find_all=True)
            devices = list(devices)
            if not devices:
                raise ValueError
        except ValueError:
            backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
            devices = usb.core.find(find_all=True, backend=backend_from_our_directory)
        if not devices:
            logger.warning("Libusb error: no usb devices was detected. Check if libusb1 is installed.")
        return list(devices)

    def produce_printer_list(self, devices):
        printers_info = []
        for dev in devices:
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
            if self.device_is_printer(dev_info):
                # try:
                #     manufacturer = dev.manufacturer  # can provoke PIPE ERROR
                #     device_dct['Manufacturer'] = manufacturer
                # except (usb.core.USBError, AttributeError, NotImplementedError):
                #     pass
                # try:
                #     product = dev.product  # can provoke PIPE ERROR
                #     device_dct['Product'] = product
                # except (usb.core.USBError, AttributeError, NotImplementedError):
                #     pass
                dev_info['SNR'] = SNR
                dev_info['COM'] = self.get_serial_port(dev_info['VID'], dev_info['PID'], SNR)
                printers_info.append(dev_info)
                #dev.close()
                #logger.debug(device_dct)
        return printers_info

    def get_serial_port(self, vid, pid, snr):
        for port_dct in serial.tools.list_ports.comports():
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
                    if snr and not 'SNR=' + snr in port_dct[2].upper():
                        continue
                    self.used_serial_ports.append(port_dct[0])
                    return port_dct[0]
        return None

    def device_is_printer(self, device):
        profiles = Config.instance().profiles
        for profile in profiles:
            if [ device['VID'], device['PID'] ] in profile[ u"vids_pids" ]:
                return True

    def get_printers(self):
        logger = logging.getLogger('app.' + __name__)
        devices = self.get_devices()
        printers = self.sort_devices(devices)
        logger.info('Detected USB printers: ')
        for printer in printers:
            logger.info(str(printer))
        logger.info('-'*16)
        return printers

if __name__ == '__main__':
    import json
    detector = USBDetector()
    for dev in detector.get_devices():
        print "\n"
        print dev
    printers = detector.get_printers()
    print json.dumps(printers)
