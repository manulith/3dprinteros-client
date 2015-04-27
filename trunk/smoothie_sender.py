import re
import raw_usb_sender
import time

class Sender(raw_usb_sender.Sender):
    def __init__(self, profile, usb_info, app):
        raw_usb_sender.Sender.__init__(self, profile, usb_info, app)
        self.temp_re = re.compile('.*ok T:([\d\.]+) /([\d\.]+) .* B:(-?[\d\.]+) /(-?[\d\.]+) .*')
        self.position_re = re.compile('Position X: ([\d\.]+), Y: ([\d\.]+), Z: ([\d\.]+)')
        self.get_temp_bed_re = re.compile('bed temp: ([\d\.]+)/([\d\.]+) @')
        self.get_temp_hotend_re = re.compile('hotend temp: ([\d\.]+)/([\d\.]+) @')
        self.bed_heating_re = re.compile('M190 S([\d\.]+)')
        self.tool_heating_re = re.compile('M109 T0 S([\d\.]+)')

    def parse_response(self, ret):
        if ret == 'ok':
            self.oks += 1
        elif ret.startswith('bed temp:') or ret.startswith('hotend temp:'):
            self.temp_request_counter -= 1
            match = self.match_temps(ret)
            if match:
                self.logger.info('TEMP UPDATE')
        elif ret.startswith('Position X:'):
            match = self.position_re.match(ret)
            if match:
                self.get_pos_counter -= 1
                self.pos_x = match.group(1)
                self.pos_y = match.group(2)
                self.pos_z = match.group(3)
                self.lift_extruder()  # It's here cause this match used only for pause. No need to implement get pos waiting logic
            else:
                self.logger.warning('Got position answer, but it does not match! Response: %s' % ret)
        else:
            self.logger.warning('Got unpredictable answer from printer: %s' % ret.decode())
            pass

    # 'get pos' command based matching for smoothie.
    def match_temps(self, request):
        match = self.get_temp_bed_re.match(request)
        if match:
            self.temps[0] = round(round(float(match.group(1)), 2))
            self.target_temps[0] = round(round(float(match.group(1)), 2))
            return True
        match = self.get_temp_hotend_re.match(request)
        if match:
            self.temps[1] = round(round(float(match.group(1)), 2))
            self.target_temps[1] = round(round(float(match.group(1)), 2))
            return True
        return False

    def pause(self):
        if not self.pause_flag:
            self.logger.info("Pausing...")
            self.pause_flag = True
            self.get_pos_counter += 1
            with self.write_lock:
                self.write('get pos')

    def temp_request(self):
        self.temp_request_counter = 0
        no_answer_counter = 0
        no_answer_cap = 5
        while not self.stop_flag:
            if self.heating_flag:
                time.sleep(1)
                #continue
            if self.temp_request_counter:
                time.sleep(2)
                no_answer_counter += 1
                if no_answer_counter >= no_answer_cap and self.temp_request_counter > 0:
                    self.temp_request_counter -= 1
            else:
                no_answer_counter = 0
                with self.write_lock:
                    self.write('get temp hotend')
                self.temp_request_counter += 1
                time.sleep(1)
                with self.write_lock:
                    self.write('get temp bed')
                self.temp_request_counter += 1