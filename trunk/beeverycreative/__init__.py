import usb.core
import usb.util
import sys
import os
import time
import logging

import utils
import usb_detect
import printrun_printer

READ_TIMEOUT = 1000
DEFAULT_READ_LENGTH = 512

class Printer(printrun_printer.Printer):

    def __init__(self, profile):
        self.logger = logging.getLogger("app." + __name__)
        if profile['COM']:
            printrun_printer.Printer.__init__(self, profile)
        else:
            self.profile = profile
            if self.init_raw_usb_device():
                self.flash_firmware()

    def find_firmware_file(self):
        firmware_dir = os.path.join(os.getcwd(), "beeverycreative", "firmware")
        for file_name in os.listdir(firmware_dir):
            if self.profile['name'].lower() in file_name.lower():
                return os.path.join(firmware_dir, file_name)

    def reset(self):
        self._printer.send_now("M609")

    def emergency_stop(self):
        self._printer.send_now("M609")
        self.stop()

    def init_raw_usb_device(self):
        print "Starting flashing initialization"
        # find our device
        int_vid = int(self.profile['VID'], 16)
        int_pid = int(self.profile['PID'], 16)
        backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
        dev = usb.core.find(idVendor=int_vid, idProduct=int_pid, backend=backend_from_our_directory)
        # set the active configuration. With no arguments, the first
        # configuration will be the active one
        dev.set_configuration()
        # get an endpoint instance
        cfg = dev.get_active_configuration()
        intf = cfg[(0,0)]
        ep_out = usb.util.find_descriptor(
            intf,
            # match the first OUT endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_OUT)
        ep_in = usb.util.find_descriptor(
            intf,
            # match the first in endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_IN)
        # Verify that the end points exist
        self.dev = dev
        self.ep_in = ep_in
        self.ep_out = ep_out
        return not ep_in or not ep_out

    #used only in raw usb mode, which we use only to flash firmware in printer
    def dispatch(self, message):
        time.sleep(0.001)
        self.ep_out.write(message)
        time.sleep(0.009)
        try:
            ret = self.ep_in.read(DEFAULT_READ_LENGTH, READ_TIMEOUT)
            sret = ''.join([chr(x) for x in ret])
        except:
            sret = "USB read timeout"
        return sret

    def flash_firmware(self):
        firmware = self.find_firmware_file()
        if firmware:
            self.logger.info("Prepare to flash device with firmware:{0}.".format(firmware))
            file_size = os.path.getsize(firmware)
            version = "0.0.0"
            ret1 = self.dispatch("M114 A{0}\n".format(version))
            message = "M650 A{0}\n".format(file_size)
            ret2 = self.dispatch(message)
            if 'ok' in ret1 and 'ok' in ret2:
                with open(firmware, 'rb') as f:
                    while True:
                        buf = f.read(64)
                        if not buf: break
                        self.ep_out.write(buf)
                        ret = []
                        while (len(ret) != len(buf)):
                            ret += self.ep_in.read(len(buf), READ_TIMEOUT)
                        assert (''.join([chr(x) for x in ret]) in buf)
                        sys.stdout.write('.')
                        sys.stdout.flush()
                self.logger.info("Flashing complete.")
                self.dispatch("M630\n")
                self.dev.reset()
                self.logger.info("Rebooting to new firmware...")

if __name__ == "__main__":
    profile = usb_detect.get_printers()[0]
    printer = Printer(profile)
    printer.reset()
    time.sleep(1)
    printer.close()




