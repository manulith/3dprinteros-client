import time
import logging
import threading
import makerbot_driver
import makerbot_serial as serial
import serial.serialutil

import base_sender

class Sender(base_sender.BaseSender):

    PAUSE_STEP_TIME = 0.5
    BUFFER_OVERFLOW_WAIT = 0.01
    IDLE_WAITING_STEP = 0.1
    TEMP_UPDATE_PERIOD = 5
    GODES_BETWEEN_READ_STATE = 100

    def __init__(self, profile, usb_info):
        base_sender.BaseSender.__init__(self, profile, usb_info)
        #self.mb = {'preheat': False, 'heat_shutdown': False}
        self.logger = logging.getLogger('app.' + __name__)
        self.logger.info('Makerbot printer created')
        self.parser = None
        self.position = None
        self.execution_lock = threading.Lock()
        self.buffer_lock = threading.Lock()
        try:
            self.parser = self.create_parser()
            self.parser.state.values["build_name"] = '3DPrinterOS'
        except Exception as e:
            self.error_code = 'No connection'
            self.error_message = str(e)
            raise RuntimeError("No connection to makerbot printer %s" % str(profile))
        else:
            self.sending_thread = threading.Thread(target=self.send_gcodes, name='PR')
            self.sending_thread.start()
            self.printing_flag = False

    def create_parser(self):
        factory = makerbot_driver.MachineFactory()
        machine = factory.build_from_port(self.profile['COM'])
        assembler = makerbot_driver.GcodeAssembler(machine.profile)
        parser = machine.gcodeparser
        start, end, variables = assembler.assemble_recipe()
        parser.environment.update(variables)
        return parser

    # def init_target_temp_regexps(self):
    #     self.platform_ttemp_regexp = re.compile('\s*M109\s*S(\d+)\s*T(\d+)')
    #     self.extruder_ttemp_regexp = re.compile('\s*M104\s*S(\d+)\s*T(\d+)')

    def lift_extruder(self):
        position = self.get_position()
        if position:
            self.position = position
            z = min(160, position[2] + 30)
            a = max(0, position[3] - 5)
            b = max(0, position[4] - 5)
            self.execute('G1  Z' + str(z) + ' A' + str(a) + ' B' + str(b))

    # length argument is used for unification with Printrun. DON'T REMOVE IT!
    def set_total_gcodes(self, length=0):
        self.parser.state.values["build_name"] = '3DPrinterOS'
        self.parser.state.percentage = 0
        self.logger.info('Begin of GCodes')
        self.parser.s3g.set_RGB_LED(255, 255, 255, 0)

    def gcodes(self, gcodes):
        gcodes = gcodes.split("\n")
        self.set_total_gcodes()
        for code in gcodes:
            with self.buffer_lock:
                self.buffer.append(code)
        self.logger.info('Enqueued block: ' + str(len(gcodes)) + ', total: ' + str(len(self.buffer)))

    def cancel(self, go_home=True):
        self.buffer.clear()
        self.printing_flag = False
        self.execute(lambda: self.parser.s3g.abort_immediately)
        if go_home:
            self.execute(lambda: self.parser.s3g.find_axes_maximums(['x', 'y'], 500, 60))
            self.execute(lambda: self.parser.s3g.find_axes_minimums(['z'], 500, 60))

    def pause(self):
        if not self.pause_flag:
            self.pause_flag = True
            time.sleep(0.1)
            self.lift_extruder()
            return True
        else:
            return False

    def unpause(self):
        if self.pause_flag:
            self.buffer.appendleft('G1 Z' + str(self.position[2]) + ' A' + str(self.position[3]) + ' B' + str(self.position[4]))
            self.pause_flag = False
            return True
        else:
            return False

    def get_position(self):
        position = self.parser.state.position.ToList()
        if position[2] is None or position[3] is None or position[4] is None:
            self.logger.warning("Can't get current tool position to execute extruder lift")
            # TODO check this is real print(can cause misprints)
            # self.position = self.execute(lambda: self.parser.s3g.get_extended_position())
            return position

    def emergency_stop(self):
        self.cancel(False)

    def immediate_pause(self):
        self.execute(self.parser.s3g.pause)

    def close(self):
        self.logger.info("Makerbot sender is closing...")
        self.stop_flag = True
        if threading.current_thread() != self.sending_thread:
            self.sending_thread.join(10)
            if self.sending_thread.isAlive():
                self.logger.error("Failed to join printing thread in makerbot_printer")
        if self.parser:
            if self.parser.s3g:
                self.parser.s3g.close()
        self.logger.info("...done closing makerbot sender.")

    def execute(self, command):
        buffer_overflow_counter = 0
        while not self.stop_flag:
            try:
                command_is_gcode = isinstance(command, str)
                if command_is_gcode:
                    text = command
                    self.printing_flag = True
                    self.execution_lock.acquire()
                    self.parser.execute_line(command)
                    self.logger.debug("Executing command: " + command)
                    result = None
                else:
                    text = command.__name__
                    self.execution_lock.acquire()
                    result = command()
            except (makerbot_driver.BufferOverflowError):
                self.execution_lock.release()
                if not buffer_overflow_counter:
                    self.logger.info('Makerbot BufferOverflow on ' + text)
                    buffer_overflow_counter += 1
                    if buffer_overflow_counter > self.GODES_BETWEEN_READ_STATE:
                        buffer_overflow_counter = 0
                        self.read_state()
                time.sleep(self.BUFFER_OVERFLOW_WAIT)
            except (serial.serialutil.SerialException, makerbot_driver.ProtocolError):
                self.logger.warning("Makerbot is retrying " + text)
                self.execution_lock.release()
            except Exception as e:
                self.logger.warning("Makerbot can't continue because of: " + e.message)
                self.error_code = 1
                self.error_message = e.message
                self.execution_lock.release()
                self.close()
                break
            else:
                self.execution_lock.release()
                return result
            # except makerbot_driver.BuildCancelledError as e:
            #except makerbot_driver.ActiveBuildError as e:
            #except makerbot_driver.Gcode.UnspecifiedAxisLocationError as e:
            #except makerbot_driver.Gcode.UnrecognizedCommandError as e:

    def read_state(self):
        platform_temp          = self.execute(lambda: self.parser.s3g.get_platform_temperature(1))
        platform_ttemp         = self.execute(lambda: self.parser.s3g.get_platform_target_temperature(1))
        head_temp1  = self.execute(lambda: self.parser.s3g.get_toolhead_temperature(0))
        head_temp2 = self.execute(lambda: self.parser.s3g.get_toolhead_temperature(1))
        head_ttemp1 = self.execute(lambda: self.parser.s3g.get_toolhead_target_temperature(0))
        head_ttemp2 = self.execute(lambda: self.parser.s3g.get_toolhead_target_temperature(1))
        #self.mb            = self.execute(lambda: self.parser.s3g.get_motherboard_status())

        self.temps = [platform_temp, head_temp1, head_temp2]
        self.target_temps = [platform_ttemp, head_ttemp1, head_ttemp2]

        #self.position      = self.execute(lambda: self.parser.s3g.get_extended_position())

    def reset(self):
        self.buffer.clear()
        try:
            self.execute(lambda: self.parser.s3g.reset())
        except Exception as e:
            self.logger.warning("Error when trying to reset makebot printer: %s" % e.message)
            self.logger.debug("DEBUG: ", exc_info=True)
        self.parser.s3g.clear_buffer()

    def is_error(self):
        return self.error_code

    def is_operational(self):
        return not self.is_error() and self.parser and self.parser.s3g.is_open() and self.sending_thread.is_alive()

    # def set_target_temps(self, command):
    #     result = self.platform_ttemp_regexp.match(command)
    #     if result is not None:
    #         self.target_temps[0] = int(result.group(1))
    #         self.logger.info('Heating platform to ' + str(result.group(1)))
    #     result = self.extruder_ttemp_regexp.match(command)
    #     if result is not None:
    #         extruder_number = int(result.group(2)) + 1
    #         self.target_temps[extruder_number] = int(result.group(1))
    #         self.logger.info('Heating toolhead ' + str(extruder_number) + ' to ' + str(result.group(1)))

    def send_gcodes(self):
        last_time = time.time()
        counter = 0
        while not self.stop_flag:
            current_time = time.time()
            if (counter >= self.GODES_BETWEEN_READ_STATE) or (current_time - last_time > self.TEMP_UPDATE_PERIOD):
                counter = 0
                last_time = current_time
                self.read_state()
            if self.pause_flag:
                self.printing_flag = False
                time.sleep(self.PAUSE_STEP_TIME)
                continue
            try:
                if not self.buffer_lock.acquire(False):
                    raise RuntimeError
                command = self.buffer.popleft()
            except RuntimeError:
                time.sleep(self.IDLE_WAITING_STEP)
            except IndexError:
                self.buffer_lock.release()
                if self.execute(lambda: self.parser.s3g.is_finished()):
                    self.printing_flag = False
                time.sleep(self.IDLE_WAITING_STEP)
            else:
                self.buffer_lock.release()
                self.execute(command)
        self.logger.info("Makerbot sender: sender thread ends.")

    def is_printing(self):
        return self.printing_flag

    def get_percent(self):
        return self.parser.state.percentage




