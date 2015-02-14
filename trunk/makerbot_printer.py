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

    def __init__(self, profile, usb_info):
        base_sender.BaseSender.__init__(self, profile, usb_info)
        #self.mb = {'preheat': False, 'heat_shutdown': False}
        self.logger = logging.getLogger('app.' + __name__)
        self.logger.info('Makerbot printer created')
        self.parser = None
        self.position = None
        self.lock = threading.Lock()
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
        self.logger.info('Enqueued block: ' + str(len(gcodes)) + ', total: ' + str(len(self.buffer)))
        for code in gcodes:
            self.buffer.append(code)

    def cancel(self):
        self.buffer.clear()
        self.printing_flag = False
        self.execute(lambda: self.parser.s3g.abort_immediately)
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
            self.logger.warning(
                'It seems that Pause/Cancel command was called in wrong command sequence(positions are None)')
            return None
        return position

    def emergency_stop(self):
        self.cancel()

    def close(self):
        self.stop_flag = True
        self.sending_thread.join(10)
        if self.parser is not None:
            if self.parser.s3g is not None:
                self.parser.s3g.close()
        if self.sending_thread.isAlive():
            self.logger.error("Failed to join printing thread in makerbot_printer")
            raise RuntimeError("Failed to join printing thread in makerbot_printer")

    def execute(self, command):
        with self.lock:
            buffer_overflow_flag = False
            while not self.stop_flag:
                try:
                    if isinstance(command, str):
                        text = command
                        self.parser.execute_line(command)
                        self.logger.debug("Executing command: " + command)
                        result = None
                    else:
                        text = command.__name__
                        result = command()

                except makerbot_driver.BufferOverflowError:
                    if not buffer_overflow_flag:
                        self.logger.info('Makerbot BufferOverflow on ' + text)
                        buffer_overflow_flag = True
                    time.sleep(self.BUFFER_OVERFLOW_WAIT)

                except serial.serialutil.SerialException as e:
                    self.logger.warning("Makerbot is retrying " + text)

                except Exception as e:
                    self.logger.warning("Makerbot can't continue because of: " + e.message)
                    self.error_code = 9
                    self.error_message = e.message
                    self.close()
                    break

                else:
                    return result

                #except makerbot_driver.BuildCancelledError as e:
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
        self.mb            = self.execute(lambda: self.parser.s3g.get_motherboard_status())

        self.temps = [platform_temp, head_temp1, head_temp2]
        self.target_temps = [platform_ttemp, head_ttemp1, head_ttemp2]

        #self.position      = self.execute(lambda: self.parser.s3g.get_extended_position())

    def reset(self):
        self.buffer.clear()
        try:
            self.parser.s3g.reset()
        except Exception as e:
            self.logger.warning("Error when trying to reset makebot printer: %s" % e.message)
            self.logger.debug("DEBUG: ", exc_info=True)
        self.parser.s3g.clear_buffer()

    def is_error(self):
        return self.error_code

    def is_operational(self):
        return not self.is_error()

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
        #self.buffer.appendleft('G28 X0 Y0 Z0')
        while not self.stop_flag:
            if self.pause_flag:
                self.printing_flag = False
                time.sleep(self.PAUSE_STEP_TIME)
                self.read_state()
                continue
            try:
                command = self.buffer.popleft()
            except IndexError:
                if self.parser.s3g.is_finished():
                    self.printing_flag = False
                time.sleep(self.IDLE_WAITING_STEP)
                self.read_state()
            else:
                if time.time() - last_time > self.TEMP_UPDATE_PERIOD:
                    self.read_state()
                self.printing_flag = True
                self.execute(command)
                #self.logger.debug('Executed GCode: ' + command)
                #self.set_target_temps(result)
                #TODO check this is real print(can cause misprints)
                #self.position = self.execute(lambda: self.parser.s3g.get_extended_position())
        self.logger.info("Makerbot sender: sender thread ends.")

    def is_printing(self):
        return self.printing_flag

    def get_percent(self):
        return self.parser.state.percentage




