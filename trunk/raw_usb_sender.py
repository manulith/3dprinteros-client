import logging
import re
import threading
import usb.core
import usb.util
import usb.backend.libusb1
import utils
import collections
import time
import base_sender
utils.init_path_to_libs()

TEMP_REQUEST_WAIT = 5
pause_lift_height = 5

int_vid = int('0x1d50', 16)
int_pid = int('0x6015', 16)

class Sender(base_sender.BaseSender):
    def __init__(self, profile, usb_info, app):

        # TODO: remove
        # self.logger = logging.getLogger("smoothie")
        # self.logger.setLevel(logging.DEBUG)
        # handler = logging.StreamHandler()
        # handler.setLevel(logging.DEBUG)
        # self.logger.addHandler
        self.logger = logging.getLogger('app.' + __name__)
        base_sender.BaseSender.__init__(self, profile, usb_info, app)

        self.logger.info('Raw USB Sender started!')

        # TODO: These are exist in base_sender, remove when adding module to app.
        # self.stop_flag = False
        # self.temps = [0, 0]
        # self.target_temps = [0, 0]

        #self.int_vid = int(usb_info['VID'], 16)
        #self.int_pid = int(usb_info['VID'], 16)
        self.end_gcodes = profile['end_gcodes']

        self.pause_flag = False
        self.printing_flag = False
        self.percent = None
        self.pos_x = None
        self.pos_y = None
        self.pos_z = None

        self.buffer = collections.deque()
        self.buffer_lock = threading.Lock()
        self.gcode_lines = None
        self.sent_gcodes = 0
        self.oks = 0
        self.temp_request_counter = 0
        self.get_pos_counter = 0

        self.temp_re = re.compile('.*ok T:([\d\.]+) /([\d\.]+) .* B:(-?[\d\.]+) /(-?[\d\.]+) .*')
        self.position_re = re.compile('Position X: ([\d\.]+), Y: ([\d\.]+), Z: ([\d\.]+)')
        self.dev = None
        self.endpoint_in = None
        self.endpoint_out = None
        self.read_thread = threading.Thread(target=self.reading)
        self.connect()
        time.sleep(2)  # Important!
        self.temp_request_thread = threading.Thread(target=self.temp_request)
        self.temp_request_thread.start()
        self.sending_thread = threading.Thread(target=self.sending)

    def connect(self):
        backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
        self.dev = usb.core.find(idVendor=int_vid, idProduct=int_pid, backend=backend_from_our_directory)
        # Checking and claiming interface 0 - interrupt interface for command sending
        # Zmorph also has interface 1 - bulk interface, assuming for file upload.
        if self.dev.is_kernel_driver_active(0) is True:
            self.logger.info('Interface is kernel active. Detaching...')
            claim_attempts = 5
            for _ in range(claim_attempts):
                try:
                    self.dev.detach_kernel_driver(0)
                    #time.sleep(0.1)
                    self.dev.set_configuration()
                    usb.util.claim_interface(self.dev, 0)
                    #time.sleep(0.1)
                except Exception as e:
                    logging.warning('Exception while detaching : %s' % e.message)
                else:
                    if self.dev.is_kernel_driver_active(0) is True:
                        self.logger.info('Can\'t detach USB device. Attempting once more...')
                    else:
                        self.logger.info('Detached and claimed!')
                        break
        else:
            self.logger.info('Interface is free. Connecting...')
        if self.dev.is_kernel_driver_active(0) is True:
            self.logger.warning('Cannot claim USB device. Aborting.')
            return False
        else:
            #self.dev.set_configuration()
            cfg = self.dev.get_active_configuration()
            self.endpoint_in = cfg[(0, 0)][0]
            self.endpoint_out = cfg[(0, 0)][1]
            self.read_thread.start()
            return True

    def write(self, gcode):
        try:
            self.endpoint_out.write(gcode + '\n', 2000)
        #except usb.core.USBError:
        except Exception as e:
            self.logger.warning('Error while writing gcode "%s"\nError: %s' % (gcode, e.message))
        else:
            print 'SENT: %s' % gcode

    def get_percent(self):
        return self.percent

    def is_printing(self):
        return self.printing_flag

    def reading(self):
        self.read()  # Clearing printer output buffer
        while not self.stop_flag:
            if not self.printing_flag:
                time.sleep(0.1)
            times_to_read = (self.sent_gcodes - self.oks) + self.temp_request_counter + self.get_pos_counter
            for _ in range(times_to_read):
                data = self.read()
                if data:
                    sret = ''.join([chr(x) for x in data])
                    if sret:
                        spret = sret.split('\n')
                        for ret in spret:
                            ret = ret.replace('\n', '')
                            ret = ret.replace('\r', '')
                            if ret:
                                self.parse_response(ret)
                    else:
                        time.sleep(0.1)
                        continue
                else:
                    continue
            time.sleep(0.1)

    def read(self):
        try:
            data = self.dev.read(self.endpoint_in.bEndpointAddress, self.endpoint_in.wMaxPacketSize, 2000)
        except Exception as e:
            self.logger.warning('Error while reading gcode: %s' % str(e))
            return None
        else:
            return data

    def is_operational(self):
        if self.printing_flag or self.pause_flag:
            return True
        if self.read_thread.is_alive() and self.temp_request_thread.is_alive():
            return True
        return False

    def parse_response(self, ret):
        if ret == 'ok':
            self.oks += 1
        elif ret.startswith('ok T:'):
            self.temp_request_counter -= 1
            #self.match_temps(ret)
            if self.match_temps(ret):
                self.logger.info('T match!')
            else:
                self.logger.info('T NOT match!')
        elif ret.startswith('Position X:'):
            match = self.position_re.match(ret)
            if match:
                self.pos_x = match.group(1)
                self.pos_y = match.group(2)
                self.pos_z = match.group(3)
                self.lift_extruder()
            else:
                self.logger.warning('Got position answer, but it does not match! Response: %s' %ret)
        else:
            #self.logger.warning('Got unpredictable answer from printer: %s' % ret.decode())
            pass

    def match_temps(self, request):
        match = self.temp_re.match(request)
        if match:
            tool_temp = float(match.group(1))
            tool_target_temp = float(match.group(2))
            platform_temp = float(match.group(3))
            platform_target_temp = float(match.group(4))
            self.temps = [platform_temp, tool_temp]
            self.target_temps = [platform_target_temp, tool_target_temp]
            #self.logger.info('Got temps: T %s/%s B %s/%s' % (tool_temp, tool_target_temp, platform_temp, platform_target_temp))
            return True
        return False

    def cancel(self):
        if self.downloading_flag:
            self.cancel_download()
            return
        self.pause_flag = False
        self.printing_flag = False
        for gcode in self.end_gcodes:
            self.write(gcode)
            time.sleep(0.1)
        self.logger.info('Cancelled!')


    def lift_extruder(self):
        gcode = 'G1 Z' + str(float(self.pos_z) + pause_lift_height)
        self.write(gcode)
        self.sent_gcodes += 1
        self.logger.info("Paused successfully")

    def pause(self):
        if not self.pause_flag:
            self.logger.info("Pausing...")
            self.pause_flag = True
            self.get_pos_counter += 1
            self.write('get pos')

    def unpause(self):
        if self.pause_flag:
            self.logger.info('Unpausing')
            gcode = 'G1 Z' + str(self.pos_z)
            self.write(gcode)
            self.sent_gcodes += 1
            self.pause_flag = False
            self.logger.info("Unpaused successfully")

    def temp_request(self):
        self.temp_request_counter = 0
        while not self.stop_flag:
            if self.temp_request_counter:
                time.sleep(0.5)
            else:
                self.temp_request_counter += 1
                self.write('M105')

    def get_current_line_number(self):
        return self.oks

    def sending(self):
        self.logger.info('Sending thread started!')
        self.gcode_lines = len(self.buffer)
        percent_step = self.gcode_lines / 100
        self.printing_flag = True
        self.percent = 0
        self.sent_gcodes = 0
        self.oks = 0
        time.sleep(0.2)  # Just let read thread start reading first
        self.logger.info('Start sending!')
        while not self.stop_flag and self.printing_flag and len(self.buffer):
            gcode = None
            if self.pause_flag:
                time.sleep(0.1)
            elif self.sent_gcodes == self.oks:
                with self.buffer_lock:
                    try:
                        gcode = self.buffer.popleft()
                    except IndexError:
                        self.logger.info('Buffer is empty!')
                if gcode is not None:  # TODO: add gcode processing. Now it is for empty gcode which is counting in self.gcode_lines
                    self.write(gcode)
                    self.sent_gcodes += 1
                    self.logger.info('Progress: %s/%s' % (self.oks, self.sent_gcodes))
                    #self.percent = self.sent_gcodes / percent_step
            else:
                time.sleep(0.1)
        self.logger.info('All gcodes are sent to printer. Waiting for finish')
        while self.oks < self.sent_gcodes:
            if not self.stop_flag:
                self.logger.info('Waiting... %s/%s' % (self.oks, self.sent_gcodes))
                time.sleep(1)
        self.logger.info('Printer has finished printing!')
        self.percent = 100
        self.printing_flag = False
        self.stop_flag = True

    def load_gcodes(self, gcodes):
        if self.printing_flag or self.pause_flag:
            self.logger.warning('Got gcodes command while job is not finished. Skipping.')
            return False
        gcodes = gcodes.split('\n')
        with self.buffer_lock:
            for line in gcodes:
                line = line.replace('\n', '')
                line = line.replace('\r', '')
                if line:
                    self.buffer.append(line)
            self.logger.info('Loaded Gcodes: %d' % len(self.buffer))
            self.sending_thread.start()
            return True

if __name__ == '__main__':
    pass
    #s = Sender()
    #time.sleep(2)  # It's very important!
    #file = 'small.gcode'
    #s.gcodes(file)
    #s.write('G28')