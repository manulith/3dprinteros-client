# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/machine/s3g.py
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

import collections
import datetime
import logging
import makerbot_driver
import threading
import time
import sys

import conveyor.error
import conveyor.log
import conveyor.machine
import conveyor.machine.port.usb

from conveyor.constants import CONSTANTS

# NOTE: The code here uses the word "profile" to refer to the
# "conveyor.machine.s3g._S3gProfile" and "s3g_profile" to refer to the
# "makerbot_driver.Profile".

class S3gDriver(conveyor.machine.Driver):
    @staticmethod
    def create(config, profile_dir, eeprom_map_dir):
        driver = S3gDriver(config, profile_dir, eeprom_map_dir)
        for profile_name in makerbot_driver.list_profiles(profile_dir):
            try:
                json_profile = makerbot_driver.Profile(profile_name, profile_dir)
                profile = _S3gProfile._create(profile_name, driver, json_profile)
            except Exception as e:
                driver._log.error("Could not load profile %s from directory %s",
                    profile_name, profile_dir, exc_info=True)
            else:
                driver._profiles[profile.name] = profile
        return driver

    def __init__(self, config, profile_dir, eeprom_map_dir):
        conveyor.machine.Driver.__init__(self, 's3g', config)
        self._profile_dir = profile_dir
        self._eeprom_map_dir = eeprom_map_dir
        self._profiles = {}

    def get_profiles(self, port):
        if None is port:
            profiles = self._profiles.values()
        else:
            profiles = []
            for profile in self._profiles.values():
                if profile._check_port(port):
                    profiles.append(profile)
        return profiles

    def get_profile(self, profile_name):
        try:
            profile = self._profiles[profile_name]
        except KeyError:
            raise conveyor.error.UnknownProfileError(profile_name)
        else:
            return profile

    def new_machine_from_port(self, port, profile):
        """ Precondition: port.machine is None """
        if None is not profile:
            s3g_profile = profile.json_profile
        else:
            machine_factory = makerbot_driver.MachineFactory(
                self._profile_dir, self._eeprom_map_dir)
            while True:
                try:
                    return_object = machine_factory.build_from_serial(
                        port.get_serial(), leaveOpen=False)
                except makerbot_driver.BuildCancelledError:
                    pass
                else:
                    break
            s3g_profile = return_object.profile
        profile = _S3gProfile._create(s3g_profile.name, self, s3g_profile)
        machine = _S3gMachine(port, self, profile)
        return machine

    def _connect(self, port, condition): # TODO: move this to the machine's `connect` since that's the only place it is currently used
        machine_factory = makerbot_driver.MachineFactory(
            self._profile_dir, self._eeprom_map_dir)
        return_object = machine_factory.build_from_serial(
            port.get_serial(), condition=condition)
        s3g = return_object.s3g
        return s3g

    def print_to_file(
            self, profile, input_path, output_path, extruders,
            extruder_temperatures, platform_temperature, heat_platform,
            material_name, build_name, job):
        try:
            with open(output_path, 'wb') as output_fp:
                condition = threading.Condition()
                writer = makerbot_driver.Writer.FileWriter(
                    output_fp, condition)
                parser = makerbot_driver.Gcode.GcodeParser()
                if (profile.json_profile.values.get('use_legacy_parser',
                                                    False)):
                    parser.state = makerbot_driver.Gcode.LegacyGcodeStates()

                parser.state.profile = profile.json_profile
                parser.state.set_build_name(str(build_name.encode(sys.getfilesystemencoding())))

                parser.s3g = makerbot_driver.s3g()
                parser.s3g.set_print_to_file_type(job.file_type)
                parser.s3g.writer = writer
                gcode_scaffold = profile.get_gcode_scaffold(
                    extruders, extruder_temperatures, platform_temperature,
                    heat_platform, material_name[0])
                parser.environment.update(gcode_scaffold.variables)
                if '.x3g' == job.file_type:
                    pid = parser.state.profile.values['PID'][0]
                    # ^ Technical debt: we get this value from conveyor local bot info, not from the profile
                    parser.s3g.x3g_version(1, 0, pid=pid) # Currently hardcode x3g v1.0

                # TODO: clear build plate message
                # parser.s3g.wait_for_button('center', 0, True, False, False)

                progress = {
                    'name': 'print-to-file',
                    'progress': 0,
                }
                job.lazy_heartbeat(progress)
                if conveyor.job.JobState.RUNNING == job.state:
                    with open(input_path) as input_fp:
                        self._execute_lines(job, parser, input_fp)
            if conveyor.job.JobState.RUNNING == job.state:
                progress = {
                    'name': 'print-to-file',
                    'progress': 100,
                }
                job.lazy_heartbeat(progress)
        except Exception as e:
            self._log.exception('unhandled exception; print-to-file failed')
            failure = conveyor.util.exception_to_failure(e)
            job.fail(failure)

    def _execute_lines(self, job, parser, iterable):
        for line in iterable:
            if conveyor.job.JobState.RUNNING != job.state:
                break
            else:
                line = str(line)
                parser.execute_line(line)
                progress = {
                    'name': 'print-to-file',
                    'progress': int(parser.state.percentage),
                }
                job.lazy_heartbeat(progress)

    def get_uploadable_machines_implementation(self):
        """
        Returns a list of machines we can upload to using s3g's firmware
        uploader.
        """
        uploader = self._create_firmware_uploader()
        machines = uploader.list_machines()
        return machines

    def get_uploadable_machines(self, job):
        def running_callback(job):
            try:
                machines = self.get_uploadable_machines_implementation()
            except Exception as e:
                self._log.exception('unhandled exception')
                failure = conveyor.util.exception_to_failure(e)
                job.fail(failure)
            else:
                job.end(machines)
        job.runningevent.attach(running_callback)
        return job

    def get_machine_versions(self, machine_type, pid, job):
        def running_callback(job):
            try:
                uploader = self._create_firmware_uploader()
                versions = uploader.list_firmware_versions(machine_type, pid)
            except Exception as e:
                self._log.exception('unhandled exception')
                failure = conveyor.util.exception_to_failure(e)
                job.fail(failure)
            else:
                job.end(versions)
        job.runningevent.attach(running_callback)
        return job

    def download_firmware(self, machine_type, pid, firmware_version, job):
        def running_callback(job):
            try:
                uploader = self._create_firmware_uploader()
                hex_file_path = uploader.download_firmware(machine_type, pid, firmware_version)
            except Exception as e:
                self._log.exception('unhandled exception')
                failure = conveyor.util.exception_to_failure(e)
                job.fail(failure)
            else:
                job.end(hex_file_path)
        job.runningevent.attach(running_callback)
        return job

    def _create_firmware_uploader(self, *args, **kwargs):
        kwargs[str('avrdude_exe')] = self._config.get('makerbot_driver', 'avrdude_exe')
        kwargs[str('avrdude_conf_file')] = self._config.get('makerbot_driver', 'avrdude_conf_file')
        uploader = makerbot_driver.Firmware.Uploader(*args, **kwargs)
        return uploader


class _S3gProfile(conveyor.machine.Profile):
    @staticmethod
    def _create(name, driver, json_profile):
        xsize = json_profile.values['axes']['X']['platform_length']
        ysize = json_profile.values['axes']['Y']['platform_length']
        zsize = json_profile.values['axes']['Z']['platform_length']
        can_print = True
        has_heated_platform = 0 != len(json_profile.values['heated_platforms'])
        number_of_tools = len(json_profile.values['tools'])
        profile = _S3gProfile(
            name, driver, xsize, ysize, zsize, json_profile, can_print,
            has_heated_platform, number_of_tools)
        return profile

    def __init__(self, name, driver, xsize, ysize, zsize, json_profile,
            can_print, has_heated_platform, number_of_tools):
        """
        Creates an s3g profile, which is returned to makerware to get
        information about the machine.

        can_print: If this machine has the ability to print (not if it
            can print right now)
        """
        conveyor.machine.Profile.__init__(
            self, name, driver, xsize, ysize, zsize, json_profile, can_print,
            has_heated_platform, number_of_tools)
        self.start_x = self.json_profile.values['print_start_sequence']['start_position']['start_x']
        self.start_y = self.json_profile.values['print_start_sequence']['start_position']['start_y']
        self.start_z = self.json_profile.values['print_start_sequence']['start_position']['start_z']

    def _check_port(self, port):
        result = (port.get_vid() == self.json_profile.values['VID']
            and port.get_pid() in self.json_profile.values['PID'])
        return result

    def get_gcode_scaffold(
            self, extruders, extruder_temperatures, platform_temperature,
            heat_platform, material_name):
        tool_0 = '0' in extruders
        tool_1 = '1' in extruders
        gcode_assembler = makerbot_driver.GcodeAssembler(
            self.json_profile, self.json_profile.path)

        #TODO wdc: determine if you should send TOM values in a differnt way?
        if('TOM' in self.json_profile.values['machinenames']):
            begin_print = 'tom_begin'
            homing = 'tom_homing'
            start_position = 'tom_start_position'
            end_start_sequence = 'tom_end_start_sequence'
            end_position = 'tom_end_position'
            end_print = 'tom_end'
        else:
            begin_print = 'replicator_begin'
            homing = 'replicator_homing'
            start_position = 'replicator_start_position'
            end_start_sequence = 'replicator_end_start_sequence'
            end_position = 'replicator_end_position'
            end_print = 'replicator_end'

        tuple_ = gcode_assembler.assemble_recipe(
            material=material_name,
            tool_0=tool_0,
            tool_1=tool_1,
            begin_print=begin_print,
            homing=homing,
            start_position=start_position,
            end_start_sequence=end_start_sequence,
            end_position=end_position,
            end_print=end_print,
            heat_platform_override=heat_platform,
            no_heat_platform_override=not heat_platform
        )
        start_template, end_template, variables = tuple_
        variables['TOOL_0_TEMP'] = extruder_temperatures[0]
        variables['TOOL_1_TEMP'] = extruder_temperatures[1]
        variables['PLATFORM_TEMP'] = platform_temperature
        start_position = self.json_profile.values['print_start_sequence']['start_position']
        variables['START_X'] = start_position['start_x']
        variables['START_Y'] = start_position['start_y']
        variables['START_Z'] = start_position['start_z']
        gcode_scaffold = conveyor.machine.GcodeScaffold()
        def append_linesep(s):
            # NOTE: do not use os.linesep here since G-code files are written
            # in text mode (Python will automagically translate the '\n' to the
            # platform's line separator).
            if not s.endswith('\n'):
                s += '\n'
            return s
        gcode_scaffold.start = map(
            append_linesep, gcode_assembler.assemble_start_sequence(
                start_template))
        gcode_scaffold.end = map(
            append_linesep, gcode_assembler.assemble_end_sequence(
                end_template))
        gcode_scaffold.variables = variables
        return gcode_scaffold


_BuildState = conveyor.enum.enum(
    '_BuildState', NONE=0, RUNNING=1, FINISHED_NORMALLY=2, PAUSED=3,
    CANCELED=4, SLEEPING=5)


class _S3gMachine(conveyor.stoppable.StoppableInterface, conveyor.machine.Machine):
    def __init__(self, port, driver, profile):
        conveyor.stoppable.StoppableInterface.__init__(self)
        conveyor.machine.Machine.__init__(self, port, driver, profile)
        self._poll_disabled = False
        self._poll_interval = 5.0
        self._poll_time = time.time()
        self._stop = False
        self._s3g = None
        self._toolhead_count = None
        self._motherboard_status = None
        self._build_stats = None
        self._platform_temperature = None
        self._is_platform_ready = None
        self._tool_status = None
        self._toolhead_temperature = None
        self._toolhead_target_temperature = None
        self._is_tool_ready = None
        self._is_finished = None
        self._operation = None
        self._job = None

        # Store the display name so that it remains accessible even if
        # the machine is disconnected. The name is defaulted to the
        # printer type, e.g. "Replicator 2".
        self._cached_display_name = self.get_profile().name

    def stop(self):
        self._stop = True
        with self._state_condition:
            self._state_condition.notify_all()

    def is_idle(self):
        with self._state_condition:
            self._poll()
            result = self._state == conveyor.machine.MachineState.IDLE
            return result

    def _parse_firmware_version(self, firmware_version):
        """
        Given a version int (i.e. 701, 604), converts it into a list of
        separate version numbers, with the last two digits being the minor version
        number, and the rest being the major number (eg. 701 --> [7, 1])
        """
        firmware_ver_str = str(firmware_version)
        firmware_list = [
            int(firmware_ver_str[:-2]),
            int(firmware_ver_str[-2:]),
        ]
        return firmware_list

    def connect(self):
        with self._state_condition:
            if self._state == conveyor.machine.MachineState.DISCONNECTED:
                self._s3g = self._driver._connect(
                    self._port, self._state_condition)
                self._firmware_version = self._parse_firmware_version(
                    self._s3g.get_version())
                self._toolhead_count = self.get_toolhead_count()
                self._cannot_cancel()
                self._change_state(conveyor.machine.MachineState.IDLE)
                self._poll()
                machine_hash = self.get_port().get_machine_hash()
                poll_thread_name = ''.join(('poll-thread-', machine_hash))
                poll_thread = threading.Thread(
                    target=self._poll_thread_target, name=poll_thread_name)
                poll_thread.start()
                work_thread_name = ''.join(('work-thread-', machine_hash))
                work_thread = threading.Thread(
                    target=self._work_thread_target, name=work_thread_name)
                work_thread.start()
        self._log.info("Connecting %r", self.get_info())

    def get_display_name(self):
        """Get the printer's LCD display name.

        This function always ends up returning the cached display
        name, which is initially the printer type. Every time this
        function is called the printer is queried for its current
        display name so that the cached value can be updated.

        If that query fails (as would happen if the printer
        disconnected) the error is logged but the cached display name
        is still returned.

        """
        try:
            if self._s3g:
                with self._state_condition:
                    self._cached_display_name = self._s3g.get_name()
        except:
            driver._log.error('Failed to get s3g display name', exc_info=True)

        return self._cached_display_name

    def cool(self, job):
        """
        Cools all extruders and platforms to 0 (if present)
        """
        info = self.get_info()
        try:
            if info["has_heated_platform"]:
                self._s3g.set_platform_temperature(0, 0)
            for i in range(info.number_of_toolheads):
                self._s3g.set_toolhead_temperature(i, 0)
        except Exception as e:
            self._log.info("Handled error cooling machine")

    def preheat(self, job, extruders, extruder_temperatures, heat_platform,
            platform_temperature):
        """
        Preheats the machine.

        @param job: Job that will run this function
        @param <int> extruders: List of extruders
        @param <int> extruder_temperatures: List of extruder temperatures.  Each
            index of this list corresponds to an extruder.  AFAICT this is always
            of length two (since we have two extruders)
        @param bool heat_platform: True if we want to heat the platform, false
            otherwise
        @param platform_temperature: Platform temperature to heat to
        """
        # TODO: Conveyor LOVES storing extruders as strings........
        extruders = map(lambda e: int(e), extruders)
        try:
            # Extruder here is an int, so we use it to index the extruder
            # temperature
            for extruder in extruders:
                self._s3g.set_toolhead_temperature(extruder,
                    extruder_temperatures[extruder])
            if heat_platform:
                self._s3g.set_platform_temperature(0, platform_temperature)
        except Exception as e:
            self._log.info("Cannot preheat.", exc_info=True)

    def get_toolhead_count(self):
        s3g_profile = self.get_profile().json_profile
        if('TOM' in s3g_profile.values['machinenames']):
            #TODO add call to s3g TOM toolhead inquirer
            return 1
        else:
            return self._s3g.get_toolhead_count()

    def disconnect(self):
        with self._state_condition:
            self._handle_disconnect()

    def pause(self):
        with self._state_condition:
            if not self._operation:
                raise conveyor.error.MachineStateException
            elif self._state == conveyor.machine.MachineState.PAUSED:
                raise conveyor.error.MachineStateException
            else:
                self._cached_state = self._state
                self._change_state(conveyor.machine.MachineState.PAUSED)
                self._operation.pause()

    def unpause(self):
        with self._state_condition:
            if not self._operation:
                raise conveyor.error.MachineStateException
            elif self._state != conveyor.machine.MachineState.PAUSED:
                raise conveyor.error.MachineStateException
            else:
                self._change_state(self._cached_state)
                self._cached_state = None
                self._operation.unpause()

    def cancel(self):
        with self._state_condition:
            if None is self._operation:
                raise conveyor.error.MachineStateException
            else:
                self._operation.cancel()

    def print(
            self, input_path, extruders, extruder_temperature,
            platform_temperature, heat_platform, material_name, build_name, job, username):
        with self._state_condition:
            self._poll()
            if self._state != conveyor.machine.MachineState.IDLE:
                self._log.info("Machine state error. Machine is at %s", self._state)
                raise conveyor.error.MachineStateException
            else:
                def cancel_print_callback(job):
                    self._operation = None
                    self._poll()
                job.cancelevent.attach(cancel_print_callback)
                self._operation = _MakeOperation(
                    self, job, input_path, extruders, extruder_temperature,
                    platform_temperature, material_name, heat_platform, build_name)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def streaming_print(self, layout_id, thingiverse_token,
                        build_name, metadata_tmp_path, job):
        with self._state_condition:
            self._poll()
            if self._state != conveyor.machine.MachineState.IDLE:
                self._log.info(
                    "Machine state error. Machine is at %s", self._state)
                raise conveyor.error.MachineStateException
            else:
                def cancel_print_callback(job):
                    self._operation = None
                    self._poll()
                job.cancelevent.attach(cancel_print_callback)
                self._operation = _StreamingMakeOperation(
                    self, job, build_name, layout_id,
                    thingiverse_token, self.get_info()['printer_type'])
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def jog(self, axis, distance_mm, duration, job):
        with self._state_condition:
            self._poll()
            if self._state == conveyor.machine.MachineState.IDLE:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _JogOperation(self, axis, distance_mm, duration, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def tom_calibration(self, job):
        with self._state_condition:
            self._poll()
            if self._state != conveyor.machine.MachineState.IDLE:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _TOMCalibrationOperation(self, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def home(self, job):
        with self._state_condition:
            self._poll()
            if self._state != conveyor.machine.MachineState.IDLE:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _HomeOperation(self, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def reset_to_factory(self, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _ResetToFactoryOperation(self, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)
                
    def change_chamber_lights(self, red, green, blue, blink_hz, brightness, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                # Brightness is ignored - not a parameter that we can use here.
                self._operation = _ChangeChamberLightsOperation(self, red, green, blue, blink_hz, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)
                
    def reset_eeprom_completely(self, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _ResetEepromCompletelyOperation(self, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def set_toolhead_temperature(self, tool_index, temperature_deg_c, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _SetToolheadTemperatureOperation(
                    self, tool_index, temperature_deg_c, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def upload_firmware(self, input_file, job):
        with self._state_condition:
            # This poll is here to make sure the machine is still active
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                # The json dicts that hold printer information are very
                # specific with what keys they want.  In particular, they want
                # something that resembles 0xB015 (the 'x' MUST be lowercase)
                pid = hex(self._port.get_pid()).upper().replace('X', 'x')
                uploadable_machines = self._driver.get_uploadable_machines_implementation()
                machine_type = None
                for _type in self.get_profile().json_profile.values['machinenames']:
                    if _type in uploadable_machines:
                        machine_type = _type
                        break
                # If we don't get a match, then s3g's firmware uploader
                # doesn't recognize this machine and we can't upload to it
                if machine_type is None:
                    raise conveyor.error.MissingMachineNameException
                self._operation = _UploadFirmwareOperation(
                    self, job, machine_type, pid, input_file)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def read_eeprom(self, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _ReadEepromOperation(self, job)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def write_eeprom(self, eeprom_map, job):
        with self._state_condition:
            self._poll()
            if conveyor.machine.MachineState.IDLE != self._state:
                raise conveyor.error.MachineStateException
            else:
                self._operation = _WriteEepromOperation(self, job, eeprom_map)
                self._can_cancel()
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def _can_cancel(self):
        with self._state_condition:
            if self._job:
                self._job.set_cancellable()

    def _cannot_cancel(self):
        with self._state_condition:
            if self._job:
                self._job.set_not_cancellable()

    def _change_state(self, new_state):
        with self._state_condition:
            if new_state != self._state:
                self._state = new_state
                self._state_condition.notify_all()
                self.state_changed(self)

    def _poll_thread_target(self):
        try:
            while not self._stop:
                with self._state_condition:
                    if conveyor.machine.MachineState.DISCONNECTED == self._state:
                        break
                    else:
                        self._poll_thread_target_iteration()
        except Exception as e:
            self._log.exception('unhandled exception; s3g poll thread has ended')
        finally:
            self._log.info('machine %s poll thread ended', self.name)

    def _poll_thread_target_iteration(self):
        if not self._poll_disabled:
            now = time.time()
            if now >= self._poll_time:
                self._poll()
            else:
                duration = self._poll_time - now
                self._state_condition.wait(duration)

    def get_motherboard_status(self):
        s3g_profile = self.get_profile().json_profile
        if('TOM' in s3g_profile.values['machinenames']):
            is_printing = not self._s3g.is_finished()
            if(is_printing):
                #TODO return a busy machine status
                return None
            else:
                return None
        else:
            return self._s3g.get_motherboard_status()

    def get_build_stats(self):
        s3g_profile = self.get_profile().json_profile
        if('TOM' in s3g_profile.values['machinenames']):
            return None
        else:
            return self._s3g.get_build_stats()

    def _poll(self):
        with self._state_condition:
            self._poll_time = time.time() + self._poll_interval
            if conveyor.machine.MachineState.DISCONNECTED != self._state:
                try:
                    motherboard_status = self.get_motherboard_status()
                    build_stats = self.get_build_stats()
                    platform_temperature = self._s3g.get_platform_temperature(0)
                    is_platform_ready = self._s3g.is_platform_ready(0)
                    tool_status = []
                    toolhead_temperature = []
                    toolhead_target_temperature = []
                    is_tool_ready = []
                    for t in range(self._toolhead_count):
                        tool_status.append(self._s3g.get_tool_status(t))
                        toolhead_target_temperature.append(
                            self._s3g.get_toolhead_target_temperature(t))
                        toolhead_temperature.append(
                            self._s3g.get_toolhead_temperature(t))
                        is_tool_ready.append(self._s3g.is_tool_ready(t))
                    is_finished = self._s3g.is_finished()
                except makerbot_driver.ActiveBuildError as e:
                    self._log.exception('machine is busy')
                    self._cannot_cancel()
                    self._change_state(conveyor.machine.MachineState.RUNNING)
                except makerbot_driver.BuildCancelledError as e:
                    self._handle_build_cancelled(e)
                except makerbot_driver.ExternalStopError as e:
                    self._handle_external_stop(e)
                except makerbot_driver.OverheatError as e:
                    self._log.exception('machine is overheated')
                    self._handle_disconnect()
                except makerbot_driver.CommandNotSupportedError as e:
                    self._log.exception('unsupported command; failed to communicate with the machine')
                    self._handle_disconnect()
                except makerbot_driver.ProtocolError as e:
                    self._log.exception('protocol error; failed to communicate with the machine')
                    self._handle_disconnect()
                except makerbot_driver.ParameterError as e:
                    self._log.exception('internal error')
                    self._handle_disconnect()
                except IOError as e:
                    self._log.exception('I/O error; failed to communicate with the machine')
                    self._handle_disconnect()
                except Exception as e:
                    self._log.exception('unhandled exception')
                    self._handle_disconnect()
                else:
                    #TODO change this
                    if(isinstance(motherboard_status, dict)):
                        busy = (motherboard_status['manual_mode']
                            or motherboard_status['onboard_script']
                            or motherboard_status['onboard_process']
                            or motherboard_status['build_cancelling'])
                    else:
                        busy = False
                    temperature_changed = (
                        self._platform_temperature != platform_temperature
                        or self._toolhead_temperature != toolhead_temperature)
                    self._log.debug(
                        'busy=%r, temperature_changed=%r, motherboard_status=%r, build_stats=%r, platform_temperature=%r, is_platform_ready=%r, tool_status=%r, toolhead_temperature=%r, is_tool_ready=%r, is_finished=%r',
                        busy, temperature_changed, motherboard_status,
                        build_stats, platform_temperature, is_platform_ready,
                        tool_status, toolhead_temperature, is_tool_ready,
                        is_finished)
                    self._motherboard_status = motherboard_status
                    self._build_stats = build_stats
                    self._platform_temperature = platform_temperature
                    self._is_platform_ready = is_platform_ready
                    self._tool_status = tool_status
                    self._toolhead_target_temperature = toolhead_target_temperature
                    self._toolhead_temperature = toolhead_temperature
                    self._is_tool_ready = is_tool_ready
                    self._is_finished = is_finished
                    if self._state == conveyor.machine.MachineState.RUNNING:
                        if not busy and self._is_finished:
                            self._can_cancel()
                            self._change_state(conveyor.machine.MachineState.IDLE)
                        elif (self._job is not None and
                                self._build_stats['BuildState'] == _BuildState.PAUSED):
                            self._job.pause()
                        # This is what checks to see if the operation is done
                    elif self._state == conveyor.machine.MachineState.PAUSED:
                        if not self._operation and self._is_finished:
                            self._can_cancel()
                            self._change_state(conveyor.machine.MachineState.IDLE)
                        elif (self._job is not None and
                                self._build_stats['BuildState'] == _BuildState.RUNNING):
                            self._job.unpause()
                    elif busy:
                        self._cannot_cancel()
                        self._change_state(conveyor.machine.MachineState.RUNNING)
                    if temperature_changed:
                        self.temperature_changed(self)
                    self._log.debug(
                        'motherboard_status=%r, build_stats=%r, platform_temperature=%r, is_platform_ready=%r, tool_status=%r, toolhead_temperature=%r, is_tool_ready=%r',
                        self._motherboard_status, self._build_stats,
                        self._platform_temperature, self._is_platform_ready,
                        self._tool_status, self._toolhead_temperature,
                        self._is_tool_ready)

    def _handle_disconnect(self):
        if None is not self._s3g:
            self._s3g.writer.close()
        self._s3g = None
        self._firmware_version = None
        self._toolhead_count = None
        self._motherboard_status = None
        self._build_stats = None
        self._platform_temperature = None
        self._is_platform_ready = None
        self._tool_status = None
        self._toolhead_temperature = None
        self._is_tool_ready = None
        self._is_finished = None
        self._operation = None
        self._job = None
        self._change_state(conveyor.machine.MachineState.DISCONNECTED)

    def _work_thread_target(self):
        try:
            while not self._stop:
                with self._state_condition:
                    if conveyor.machine.MachineState.DISCONNECTED == self._state:
                        break
                    else:
                        self._work_thread_target_iteration()
        except Exception as e:
            self._log.exception('unhandled exception; s3g work thread ended')
        finally:
            self._handle_disconnect()
            self._log.info('machine %s work thread ended', self.name)

    def _work_thread_target_iteration(self):
        self._log.debug('operation=%r', self._operation)
        if self._operation is not None:
            try:
                self._operation.run()
            finally:
                self._operation = None
        self._state_condition.wait()

    def _handle_build_cancelled(self, exception):
        self._log.debug('handled exception', exc_info=True)
        if (None is not self._job
                and conveyor.job.JobState.STOPPED != self._job.state):
            self._job.cancel()
            self._job = None

    def _handle_external_stop(self, exception):
        self._log.debug('handled exception', exc_info=True)
        if (None is not self._job
                and conveyor.job.JobState.STOPPED != self._job.state):
            self._job.cancel()
            self._job = None
        self._s3g.writer.set_external_stop(False)


class _S3gOperation(object):
    def __init__(self, machine):
        self.machine = machine
        self.log = conveyor.log.getlogger(self)

    def run(self):
        raise NotImplementedError

    def pause(self):
        raise NotImplementedError

    def unpause(self):
        raise NotImplementedError

    def cancel(self):
        raise NotImplementedError


class _JobOperation(_S3gOperation):
    def __init__(self, machine, job):
        _S3gOperation.__init__(self, machine)
        self.job = job

    def run(self):
        self.machine._job = self.job
        try:
            self._run_job()
        finally:
            self.machine._job = None

    def _run_job(self):
        raise NotImplementedError


class _BlockPollingOperation(_JobOperation):
    def _run_job(self):
        self.machine._poll_disabled = True
        try:
            self._run_without_polling()
        finally:
            self.machine._poll_disabled = False

    def _run_without_polling(self):
        raise NotImplementedError


class _SetToolheadTemperatureOperation(_JobOperation):
    def __init__(self, machine, tool_index, temperature_deg_c, job):
        _JobOperation.__init__(self, machine, job)
        self.tool_index = tool_index
        self.temperature_deg_c = temperature_deg_c

    def _run_job(self):
        try:
            self.machine._s3g.set_toolhead_temperature(self.tool_index,
                                                       self.temperature_deg_c)
        except Exception as e:
            self.log.exception('unhandled exception; '
                               'set_toolhead_temperature failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)

class _ChangeChamberLightsOperation(_JobOperation):
    def __init__(self, machine, red, green, blue, blink_hz, job):
        _JobOperation.__init__(self, machine, job)
        self.red = red
        self.green = green
        self.blue = blue
        # Educated guess - blink rate range of LEDs goes from 0.2 hz to ~50 hz with an LSB of 0.0196 secs
        self.BLINK_LSB_SECS = 0.0196
        if (blink_hz > (1 / self.BLINK_LSB_SECS))  or (blink_hz <= 0):
            self.blink_rate = 0
        elif blink_hz < (1 / (255 * self.BLINK_LSB_SECS)):
            self.blink_rate = 255
        else:
            self.blink_rate = ((1.0 / blink_hz) / self.BLINK_LSB_SECS)
            
    def _run_job(self):
        try:
            self.machine._s3g.set_RGB_LED(self.red, self.green, self.blue, self.blink_rate)
        except Exception as e:
            self.log.exception('unhandled exception; '
                               'set_RGB_LED failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)            

class _JogOperation(_JobOperation):
    def __init__(self, machine, axis, distance_mm, duration, job):
        _JobOperation.__init__(self, machine, job)
        self.axis = axis.upper()
        self.distance_mm = distance_mm
        self.duration = duration

    def _run_job(self):
        try:
            # Attach callback to stop jogging
            def cancel_callback(job):
                with self.machine._state_condition:
                    self.machine._s3g.extended_stop(True, True)
            self.job.cancelevent.attach(cancel_callback)

            if self.axis in ['X','Y','Z','A','B']:
                axis_values = self.convert_from_mm_to_steps()
            else:
                try:
                    raise ValueError
                except Exception as e:
                    self.log.exception('axis specified in jog job is not a valid axis')
                    failure = conveyor.util.exception_to_failure(e)
                    self.job.fail(failure)
            axes = ['X','Y','Z','A','B']
            self.machine._s3g.queue_extended_point_new(axis_values, self.duration, axes)
            self.machine._state_condition.wait(.1)
        except makerbot_driver.BuildCancelledError as e:
            self.machine._handle_build_cancelled(e)
        except makerbot_driver.ExternalStopError as e:
            self.machine._handle_external_stop(e)
        except Exception as e:
            self.log.exception('unhandled exception; jog failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)

    def convert_from_mm_to_steps(self):
        s3g_profile = self.machine._profile.json_profile
        axis_values = ['X','Y','Z','A','B']
        axis_index = axis_values.index(self.axis)
        axis_values = [0,0,0,0,0]
        axis_values[axis_index] = self.distance_mm * s3g_profile.values['axes'][self.axis]['steps_per_mm']
        return axis_values

#TODO make this inherit from _HomeOperation so we can use the get feedrate stuffs
class _TOMCalibrationOperation(_JobOperation):
    def __init__(self, machine, job):
        _JobOperation.__init__(self, machine, job)
        #TODO get this feedrate from the profile
        self.feedrate = 600
        self.timeout = 20

    def _run_job(self):
        try:
            self.machine._s3g.toggle_axes(['x','y','z'], True)
            self.machine._state_condition.wait(.1)
            self.machine._s3g.set_extended_position([0,0,0,0,0])
            self.machine._state_condition.wait(.1)
            self.machine._s3g.find_axes_maximums(['z'], self.feedrate, self.timeout)
            self.machine._state_condition.wait(.1)
            self.machine._s3g.find_axes_minimums(['x','y'], self.feedrate, self.timeout)
            self.machine._state_condition.wait(.1)
            self.machine._s3g.store_home_positions(['x','y','z'])
            self.machine._state_condition.wait(.1)
            self.machine._s3g.toggle_axes(['x','y','z'], False)
            self.machine._state_condition.wait(.1)

        except makerbot_driver.BuildCancelledError as e:
            self.machine._handle_build_cancelled(e)
        except makerbot_driver.ExternalStopError as e:
            self.machine._handle_external_stop(e)
        except Exception as e:
            self.log.exception('unhandled exception; calibration failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        self.job.end(None)


class _HomeOperation(_JobOperation):
    def __init__(self, machine, job):
        _JobOperation.__init__(self, machine, job)
        self.timeout = 20
    def _run_job(self):
        s3g_profile = self.machine.get_profile().json_profile
        axes_feedrates = self._get_feedrates(s3g_profile)
        try:
            if('TOM' in s3g_profile.values['machinenames']):
                self.machine._s3g.toggle_axes(['x','y','z'], True)
                self.machine._state_condition.wait(.1)
                self.machine._s3g.find_axes_maximums(['z'], axes_feedrates['z'], self.timeout)
                self.machine._state_condition.wait(.1)
                #Assume x & y have the same feedrate constraints
                self.machine._s3g.find_axes_minimums(['x','y'], axes_feedrates['x'], self.timeout)
                self.machine._state_condition.wait(.1)
                self.machine._s3g.toggle_axes(['x','y','z'], False)
                self.machine._state_condition.wait(.1)
            else:
                self.machine._s3g.toggle_axes(['x','y','z'], True)
                self.machine._state_condition.wait(.1)
                #Assume x & y have the same feedrate constraints
                self.machine._s3g.find_axes_maximums(['x','y'], axes_feedrates['x'], self.timeout)
                self.machine._state_condition.wait(.1)
                self.machine._s3g.find_axes_minimums(['z'], axes_feedrates['z'], self.timeout)
                self.machine._state_condition.wait(.1)
                self.machine._s3g.toggle_axes(['x','y','z'], False)
                self.machine._state_condition.wait(.1)
        except makerbot_driver.ExternalStopError as e:
            self.machine._handle_external_stop(e)
        except Exception as e:
            self.log.exception('unhandled exception; home failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        self.job.end(None)

    def _get_feedrates(self, s3g_profile):
        axes = ['x','y','z']
        axes_feedrates = {
            'x': None,
            'y': None,
            'z': None
        }
        for axis in axes:
            axes_feedrates[axis] = self._calculate_microsecs_per_step(axis, s3g_profile)
        #Set x and y both to the larger feedrate since they home at the same time
        #A greater feedrate = slower movement
        axes_feedrates['x'] = axes_feedrates['y'] = max(axes_feedrates['y'], axes_feedrates['x'])
        return axes_feedrates

    def _calculate_microsecs_per_step(self, axis, s3g_profile):
        MICROSECONDS_PER_MINUTE = 60000000
        axis = axis.upper()
        #max feedrate in mm/minute
        max_axis_feedrate = float(s3g_profile.values['axes'][axis]['max_feedrate'])
        safe_feedrate = max_axis_feedrate/2
        axis_length = s3g_profile.values['axes'][axis]['platform_length']
        steps_per_mm = s3g_profile.values['axes'][axis]['steps_per_mm']
        max_time_microseconds = (axis_length/safe_feedrate)*MICROSECONDS_PER_MINUTE
        axis_length_steps = axis_length * steps_per_mm
        return max_time_microseconds/axis_length_steps


class _PrintToBotOperation(_JobOperation):
    def __init__(self, machine, job, build_name):
        _JobOperation.__init__(self, machine, job)
        self.input_path = input_path
        self.extruders = extruders
        self.extruder_temperature = extruder_temperature
        self.platform_temperature = platform_temperature
        self.material_name = material_name
        self.build_name = build_name
        self.heat_platform = heat_platform
        self.paused = False

    def _run_job(self):
        try:
            parser = makerbot_driver.Gcode.GcodeParser()
            if (self.machine._profile.json_profile.values.get(
                    'use_legacy_parser', False)):
                parser.state = makerbot_driver.Gcode.LegacyGcodeStates()

            parser.state.profile = self.machine._profile.json_profile
            parser.state.set_build_name(str(self.build_name.encode(sys.getfilesystemencoding())))

            parser.s3g = self.machine._s3g
            def cancel_callback(job):
                with self.machine._state_condition:
                    parser.s3g.abort_immediately()
                    try:
                        parser.s3g.writer.set_external_stop(True)
                    except makerbot_driver.ExternalStopError:
                        self.log.debug('handled exception', exc_info=True)
            self.job.cancelevent.attach(cancel_callback)
            # We do this only to get the start_end variables
            gcode_scaffold = self.machine._profile.get_gcode_scaffold(
                self.extruders, self.extruder_temperature,
                self.platform_temperature, self.heat_platform,
                self.material_name[0])
            parser.environment.update(gcode_scaffold.variables)
            if self.machine._s3g.get_version() >= 700:
                pid = parser.state.profile.values['PID'][0]
                # ^ Technical debt: we get this value from conveyor local bot info, not from the profile
                parser.s3g.x3g_version(1, 0, pid=pid) # Currently hardcode x3g v1.0
            # dgs3 imagines we do a reset here to clear out the output buffer
            # on the machine
            self.machine._s3g.reset()
            # Aaaaaaaaaargh. :'(
            #
            # progress = {
            #     'name': 'clear-build-plate',
            #     'progress': 0,
            # }
            # self.job.lazy_heartbeat(progress)
            # self.machine._s3g.display_message(0, 0, str('clear'), 0, True, True, False)
            # self.machine._s3g.wait_for_button('center', 0, True, False, False)
            # while self.machine._motherboard_status['wait_for_button']:
            #     self.machine._state_condition.wait(0.2)
            progress = {
                'name': 'print',
                'progress': 0,
            }
            self.job.lazy_heartbeat(progress)
            if conveyor.job.JobState.RUNNING == self.job.state:

                with self._create_iterable() as iterable:
                    self._execute_lines(parser, iterable)

            if conveyor.job.JobState.RUNNING == self.job.state:
                progress = {
                    'name': 'print',
                    'progress': 100,
                }
                self.job.lazy_heartbeat(progress)
                self.job.end(True)
        except makerbot_driver.BuildCancelledError as e:
            self.machine._handle_build_cancelled(e)
        except makerbot_driver.ExternalStopError as e:
            self.machine._handle_external_stop(e)
        except Exception as e:
            self.log.exception('unhandled exception; print failed')
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)

    def _execute_lines(self, parser, iterable):
        count = 0
        total_time = 0
        for line in iterable:
            # OUTER LOOP: executed once per line of G-code
            count += 1
            line = self._clean_line(line)
            self.log.debug('RAW COMMAND [%d]: %s', count, line)
            while True:
                # INNER LOOP: executed until the job is canceled or the G-code
                # is sent without a buffer overflow
                if self.job.state not in [conveyor.job.JobState.RUNNING,
                                          conveyor.job.JobState.PAUSED,]:
                    # Breaking if the machine isn't running or paused seems
                    # like a waste -- why bother processing the rest of the
                    # commands if the print is cancelled? Return instead,
                    # unless there's a reason not to.
                    return
                    #break
                elif self.paused:
                    self.machine._state_condition.wait(1.0)
                else:
                    start = datetime.datetime.now()
                    try:
                        parser.execute_line(line)
                    except makerbot_driver.BufferOverflowError:
                        # NOTE: too spammy
                        # self.log.debug('handled exception', exc_info=True)
                        self.machine._state_condition.wait(0.2)
                        # NOTE: this branch WILL NOT break out of the inner
                        # `while` loop. The interpreter will attempt to re-send
                        # the current line of G-code (assuming the job is
                        # still running and the machine is not paused).
                    else:
                        progress = {
                            'name': 'print',
                            'progress': int(parser.state.percentage),
                        }
                        self.job.lazy_heartbeat(progress)
                        # NOTE: this branch WILL break out of the inner `while`
                        # loop but NOT the outer `for` loop. The interpreter
                        # will advance to the next line of G-code.
                        break
                    finally:
                        end = datetime.datetime.now()
                        total_time += (end - start).total_seconds()
                        self.job.add_extra_info("elapsed_time", int(round(total_time)))

    def pause(self):
        with self.machine._state_condition:
            build_state = self.machine.get_build_stats()['BuildState']
            if not build_state == _BuildState.PAUSED:
                self.paused = True
                self.machine._s3g.pause() # NOTE: this toggles the pause state
                self.machine._state_condition.notify_all()

    def unpause(self):
        with self.machine._state_condition:
            build_state = self.machine.get_build_stats()['BuildState']
            if build_state == _BuildState.PAUSED:
                self.paused = False
                self.machine._s3g.pause() # NOTE: this toggles the pause state
                self.machine._state_condition.notify_all()

    def cancel(self):
        if self.job.state in [conveyor.job.JobState.RUNNING,
                              conveyor.job.JobState.PAUSED]:
            self.job.cancel()


    ### For subclasses
    def _initiate_parser(self):
        raise NotImplementedError

    def _create_iterable(self):
        raise NotImplementedError


class _StreamingMakeOperation(_PrintToBotOperation):
    def __init__(self, machine, job, build_name,
                 layout_id, thingiverse_token, printer_type):
        _PrintToBotOperation.__init__(self, machine, job, build_name)
        self.layout_id = layout_id
        self.thingiverse_token = thingiverse_token
        self.printer_type = printer_type

    def _initiate_parser(self):
        self.parser = makerbot_driver.Streaming.X3GParser()
        self.parser.state.profile = self.machine._profile.json_profile
        self.parser.state.set_build_name(str(self.build_name))
        self.parser.s3g = self.machine._s3g
        return self.parser

    def _create_iterable(self):
        self.stream = makerbot_driver.Streaming.X3GStream(
            CONSTANTS["DIGITAL_STORE"]["STREAMING"],
            self.layout_id,
            self.thingiverse_token,
            self.printer_type)
        return self.stream

    def _clean_line(self, line):
        ### X3G is already good, it's a no-op
        return line

class _MakeOperation(_PrintToBotOperation):
    def __init__(self, machine, job, input_path, extruders,
                 extruder_temperature, platform_temperature,
                 material_name, heat_platform, build_name):
        _PrintToBotOperation.__init__(self, machine, job, build_name)
        self.input_path = input_path
        self.extruders = extruders
        self.extruder_temperature = extruder_temperature
        self.platform_temperature = platform_temperature
        self.material_name = material_name
        self.heat_platform = heat_platform

    def _initiate_parser(self):
        parser = makerbot_driver.Gcode.GcodeParser()
        if (self.machine._profile.json_profile.values.get(
                'use_legacy_parser', False)):
            parser.state = makerbot_driver.Gcode.LegacyGcodeStates()

        parser.state.profile = self.machine._profile.json_profile
        parser.state.set_build_name(
            str(self.build_name.encode(sys.getfilesystemencoding())))
        parser.s3g = self.machine._s3g
        gcode_scaffold = self.machine._profile.get_gcode_scaffold(
                            self.extruders, self.extruder_temperature,
                            self.platform_temperature, self.heat_platform,
                            self.material_name[0])
        parser.environment.update(gcode_scaffold.variables)
        return parser

    def _create_iterable(self):
        return open(self.input_path)

    def _clean_line(self, line):
        line = str(line) # NOTE: s3g can't handle unicode.
        line = line.strip()
        return line

class _ResetToFactoryOperation(_BlockPollingOperation):
    def _run_without_polling(self):
        try:
            self.machine._s3g.reset_to_factory()
            self.machine._s3g.reset()
        except Exception as e:
            self.log.warning('handled exception', exc_info=True)
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        else:
            self.job.end(None)


class _ResetEepromCompletelyOperation(_BlockPollingOperation):
    def __init__(self, machine, job):
        _JobOperation.__init__(self, machine, job)

    def _run_without_polling(self):
        try:
            version = str(self.machine._s3g.get_version())
            try:
                advanced_version = self.machine._s3g.get_advanced_version()
                software_variant = hex(advanced_version['SoftwareVariant'])
                if len(software_variant.split('x')[1]) == 1:
                    software_variant = software_variant.replace('x', 'x0')
            except makerbot_driver.errors.CommandNotSupportedError:
                software_variant = '0x00'
            version = _get_version_with_dot(version)
            persistent_info = self._get_persistent_info(version, software_variant)
            working_directory = self.machine._driver._config.get(
                'makerbot_driver', 'eeprom_dir')
            eeprom_writer = makerbot_driver.EEPROM.EepromWriter.factory(
                self.machine._s3g, version, software_variant,
                working_directory)
            eeprom_writer.reset_eeprom_completely()
            self.machine._s3g.reset()
            self._write_persistent_info(persistent_info, version, software_variant)
            self.machine._s3g.reset_to_factory()
            self._upload_ToM_default_settings(eeprom_writer)
            self.machine._s3g.reset()
        except Exception as e:
            self.log.warning('handled exception', exc_info=True)
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        self.job.end(None)

    def _upload_ToM_default_settings(self, eeprom_writer):
        #If the bot is a TOM write out the max feedrate for all axes
        #Sailfish default maxes are a bit off
        if('TOM' in self.machine.get_profile().name):
            s3g_profile = self.machine.get_profile().json_profile
            for axis in s3g_profile.values['axes'].iterkeys():
                max_feedrate = s3g_profile.values['axes'][axis]['max_feedrate']
                eeprom_writer.write_data(str('ACCEL_MAX_FEEDRATE_' + axis), max_feedrate)
            eeprom_writer.flush_data()

    def _get_persistent_info(self, dotted_version, software_variant):
        #Grab these values now and restore them after EEPROM is wiped
        working_directory = self.machine._driver._config.get('makerbot_driver', 'eeprom_dir')
        eeprom_reader = makerbot_driver.EEPROM.EepromReader.factory(
            self.machine._s3g, dotted_version, software_variant, working_directory)
        info = {
            'TOOL_COUNT': eeprom_reader.read_data('TOOL_COUNT'),
            'HBP_PRESENT': None,
            'TOOLHEAD_OFFSET_SETTINGS_UM': None,
            'TOOLHEAD_OFFSET_SETTINGS': None
        }
        #TOMs don't have this field in EEPROM
        if(not 'TOM' in self.machine.get_profile().name):
            info['HBP_PRESENT'] = eeprom_reader.read_data('HBP_PRESENT')
        #Nested try-except due to difference in key names in old vs new firmware
        try:
            toolhead_key = 'TOOLHEAD_OFFSET_SETTINGS_UM'
            toolhead_offsets = eeprom_reader.read_data(toolhead_key)
        except KeyError:
            try:
                toolhead_key = 'TOOLHEAD_OFFSET_SETTINGS'
                toolhead_offsets = eeprom_reader.read_data(toolhead_key)
            except KeyError:
                toolhead_offsets = None
        info[toolhead_key] = toolhead_offsets
        return info

    def _write_persistent_info(self, persistent_info, dotted_version, software_variant):
        #Writing these values back into eeprom as they are important for machine
        #detection and user-friendliness of the machine
        working_directory = self.machine._driver._config.get(
            'makerbot_driver', 'eeprom_dir')
        eeprom_writer = makerbot_driver.EEPROM.EepromWriter.factory(
            self.machine._s3g, dotted_version, software_variant,
                working_directory)
        for key in persistent_info:
            if(persistent_info[key] != None):
                eeprom_writer.write_data(str(key), persistent_info[key])
        eeprom_writer.flush_data()


class _UploadFirmwareOperation(_BlockPollingOperation):
    def __init__(self, machine, job, machine_type, pid, input_file):
        _JobOperation.__init__(self, machine, job)
        self.machine_type = machine_type
        self.input_file = input_file
        self.pid = pid

    def _run_without_polling(self):
        try:
            self.machine._s3g.writer.file.close()
            port = self.machine.get_port()
            driver = self.machine.get_driver()
            uploader = driver._create_firmware_uploader()
            uploader.upload_firmware(
                port.get_serial_port_name(), self.machine_type, self.pid, self.input_file)
            self.machine._s3g.writer.file.open()
        except Exception as e:
            self.log.warning('handled exception', exc_info=True)
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        else:
            self.job.end(None)


class _ReadEepromOperation(_BlockPollingOperation):
    def _run_without_polling(self):
        try:
            version = str(self.machine._s3g.get_version())
            try:
                advanced_version = self.machine._s3g.get_advanced_version()
                software_variant = hex(advanced_version['SoftwareVariant'])
                if len(software_variant.split('x')[1]) == 1:
                    software_variant = software_variant.replace('x', 'x0')
            except makerbot_driver.errors.CommandNotSupportedError:
                software_variant = '0x00'
            version = _get_version_with_dot(version)
            working_directory = self.machine._driver._config.get('makerbot_driver', 'eeprom_dir')
            eeprom_reader = makerbot_driver.EEPROM.EepromReader.factory(
                self.machine._s3g, version, software_variant, working_directory)
            eeprom_map = eeprom_reader.read_entire_map()
        except Exception as e:
            self.log.warning('handled exception', exc_info=True)
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        else:
            self.job.end(eeprom_map)


class _WriteEepromOperation(_BlockPollingOperation):
    def __init__(self, machine, job, eeprom_map):
        _BlockPollingOperation.__init__(self, machine, job)
        self.eeprom_map = eeprom_map

    def _run_without_polling(self):
        try:
            version = str(self.machine._s3g.get_version())
            try:
                advanced_version = self.machine._s3g.get_advanced_version()
                software_variant = hex(advanced_version['SoftwareVariant'])
                if len(software_variant.split('x')[1]) == 1:
                    software_variant = software_variant.replace('x', 'x0')
            except makerbot_driver.errors.CommandNotSupportedError:
                software_variant = '0x00'
            version = _get_version_with_dot(version)
            working_directory = self.machine._driver._config.get(
                'makerbot_driver', 'eeprom_dir')
            eeprom_writer = makerbot_driver.EEPROM.EepromWriter.factory(
                self.machine._s3g, version, software_variant,
                working_directory)
            eeprom_writer.write_entire_map(self.eeprom_map)
        except Exception as e:
            self.log.warning('handled exception', exc_info=True)
            failure = conveyor.util.exception_to_failure(e)
            self.job.fail(failure)
        else:
            self.job.end(None)


def _get_version_with_dot(version):
    if len(version) != 3:
        raise ValueError(version)
    else:
        if '0' == version[1]:
            version = version[0] + '.' + version[2]
        else:
            version = version[0] + '.' + version[1:2]
        return version
