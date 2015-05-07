import re
import raw_usb_sender
import time
import usb.core
import os
import sys
import utils

#vid: FFFF
#pid: 014E
#T:13.1999 B:0.0000 ok Q:0
#E: Bad code ok Q:1

# SENT: M140 S0
# Parsing ok - E: Bad M-code 140

#SENT: M84
#Parsing ok - E: Bad M-code 84

#SENT: M29
#Parsing ok - E: Bad M-code 29

class Sender(raw_usb_sender.Sender):

    TEMP_REQUEST_GCODE = 'M105'

    def __init__(self, profile, usb_info, app):
        raw_usb_sender.Sender.__init__(self, profile, usb_info, app)
        self.define_regexps()
        self.logger.info('Beeverycreative Sender started!')

    def connect(self):
        print "Beetf connecting!"
        # find our device
        int_vid = int(self.usb_info['VID'], 16)
        int_pid = int(self.usb_info['PID'], 16)
        backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
        dev = usb.core.find(idVendor=int_vid, idProduct=int_pid, backend=backend_from_our_directory)
        # set the active configuration. With no arguments, the first
        # configuration will be the active one
        if dev.is_kernel_driver_active(0) is True:
            print 'Detach!'
            dev.detach_kernel_driver(0)
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
        self.endpoint_in = ep_in
        self.endpoint_out = ep_out
        return True

    def define_regexps(self):
        self.temp_re = re.compile('T:([\d\.]+) B:([\d\.]+) ok Q:([\d\.]+)')

    def define_endpoints(self):
        self.endpoint_in = 0x81
        self.endpoint_out = 0x1

    def parse_response(self, ret):
        self.logger.info('Parsing %s' % ret)
        if ret.startswith('ok'):
            self.oks += 1
        elif ret.startswith('T:'):
            self.temp_request_counter -= 1
            match = self.match_temps(ret)
            if match:
                self.logger.info('TEMP UPDATE')
        else:
            self.logger.debug('Got unpredictable answer from printer: %s' % ret.decode())

    # M105 based matching. Redefine if needed.
    def match_temps(self, request):
        match = self.temp_re.match(request)
        if match:
            tool_temp = float(match.group(1))
            #tool_target_temp = float(match.group(2))
            platform_temp = float(match.group(2))
            #platform_target_temp = float(match.group(4))
            self.temps = [platform_temp, tool_temp]
            #self.target_temps = [platform_target_temp, tool_target_temp]
            #self.logger.info('Got temps: T %s/%s B %s/%s' % (tool_temp, tool_target_temp, platform_temp, platform_target_temp))
            return True
        return False

    def prepare_printer(self):
        self.logger.info('Checking if beetf firmware working')
        self.write('M105')
        time.sleep(0.1)
        if self.read():
            self.logger.info('Firmware is working!')
        else:
            self.logger.info('Firmware is not working')
            self.flash_firmware()

    def find_firmware_file(self):
        firmware_dir = os.path.join(os.getcwd(), "firmware")
        for file_name in os.listdir(firmware_dir):
            if 'beethefirst' in file_name.lower():
                firmware = os.path.join(firmware_dir, file_name)
                return firmware

    def flash_firmware(self):
        firmware = self.find_firmware_file()
        if firmware:
            self.logger.info("Prepare to flash device with firmware:{0}.".format(firmware))
            file_size = os.path.getsize(firmware)
            version = "0.0.0"
            self.write("M114 A{0}".format(version))
            time.sleep(0.1)
            ret1 = self.read()
            message = "M650 A{0}".format(file_size)
            self.write(message)
            time.sleep(0.1)
            ret2 = self.read()
            if ret1 and ret2 and 'ok' in ret1 and 'ok' in ret2:
                with open(firmware, 'rb') as f:
                    while True:
                        buf = f.read(64)
                        if not buf:
                            break
                        self.write(buf)
                        ret = []
                        while (len(ret) != len(buf)):
                            ret += self.read()
                        assert (''.join([chr(x) for x in ret]) in buf)
                        sys.stdout.write('.')
                        sys.stdout.flush()
                self.logger.info("Flashing complete.")
                self.write("M630")
                self.dev.reset()
                self.logger.info("Rebooting to new firmware...")
        else:
            self.logger.warning("Error - no firmware found.")

    def pause(self):
        pass
        # if not self.pause_flag:
        #     self.logger.info("Pausing...")
        #     self.pause_flag = True
        #     self.get_pos_counter += 1
        #     with self.write_lock:
        #         self.write('get pos')

    def temp_request(self):
        while not self.stop_flag:
            time.sleep(2)
            with self.write_lock:
                self.write(self.TEMP_REQUEST_GCODE)

    def read(self):
        try:
            print 'Reading...'
            #data = self.dev.read(self.endpoint_in.bEndpointAddress, self.endpoint_in.wMaxPacketSize, 2000)
            data = self.endpoint_in.read(64, 2000)
        except usb.core.USBError as e:
            self.logger.info('USBError : %s' % str(e))
            # TODO: parse ERRNO 110 here to separate timeout exceptions | [Errno 110] Operation timed out
            return None
        except Exception as e:  # TODO: make not operational
            self.logger.warning('Error while reading gcode: %s' % str(e))
            return None
        else:
            return data

    def write(self, gcode):
        try:
            print 'Writing...'
            self.endpoint_out.write(gcode + '\n')
        #except usb.core.USBError:
        except Exception as e:
            self.logger.warning('Error while writing gcode "%s"\nError: %s' % (gcode, e.message))
        else:
            print 'SENT: %s' % gcode