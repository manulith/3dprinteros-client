# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/machine/__init__.py
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

import logging
import threading

import conveyor.enum
import conveyor.error
import conveyor.event
import conveyor.log
import conveyor.stoppable


class DriverManager(object):
    """
    Object to manage the panoply of drivers we support.
    """
    @staticmethod
    def create(config):
        driver_manager = DriverManager()

        import conveyor.machine.s3g
        profile_dir = config.get('makerbot_driver', 'profile_dir')
        eeprom_dir = config.get('makerbot_driver', 'eeprom_dir')
        driver = conveyor.machine.s3g.S3gDriver.create(config, profile_dir, eeprom_dir)
        driver_manager._drivers[driver.name] = driver

        import conveyor.machine.birdwing
        birdwing_profile_dir = config.get('embedded', 'profile_dir')
        birdwing_driver = conveyor.machine.birdwing.BirdWingDriver.create(config, birdwing_profile_dir)
        driver_manager._drivers[birdwing_driver.name] = birdwing_driver

        # import conveyor.machine.digitizer
        # profile_dir = config.get('digitizer', 'profile_dir')
        # driver = conveyor.machine.digitizer.DigitizerDriver.create(config, profile_dir)
        # driver_manager._drivers[driver.name] = driver

        # Add more drivers here.

        return driver_manager

    def __init__(self):
        self._drivers = {}

    def get_drivers(self):
        return self._drivers.values()

    def get_driver(self, driver_name):
        try:
            driver = self._drivers[driver_name]
        except KeyError:
            raise conveyor.error.UnknownDriverError(driver_name)
        else:
            return driver

    def get_from_profile(self, profile_name):
        for driver in self._drivers.values():
            try:
                profile = driver.get_profile(profile_name)
            except:
                pass
            else:
                return (driver, profile)
        raise conveyor.error.UnknownProfileError(profile_name)

class Driver(object):
    def __init__(self, name, config):
        self.name = name
        self._config = config
        self._log = conveyor.log.getlogger(self)

    def get_profiles(self, port):
        raise NotImplementedError

    def get_profile(self, profile_name):
        raise NotImplementedError

    def new_machine_from_port(self, port, profile):
        """ Precondition: port.machine is None """
        raise NotImplementedError

    def print_to_file(
            self, profile, input_file, output_file, has_start_end,
            extruders, extruder_temperature, platform_temperature,
            material_name, build_name, job):
        raise NotImplementedError

    def get_info(self):
        return {
            "name": self.name,
            "profiles": map(lambda profile: profile.get_info(),
                self.get_profiles(None)),
        }

    # TODO: these are specific to S3G.

    def get_uploadable_machines(self, job):
        raise NotImplementedError

    def get_machine_versions(self, machine_type, job):
        raise NotImplementedError

    def download_firmware(self, machine_type, pid, firmware_version, job):
        raise NotImplementedError

class Profile(object):
    def __init__(self, name, driver, xsize, ysize, zsize, json_profile,
            can_print, has_heated_platform, number_of_tools):
        self.name = name
        self.driver = driver
        self.xsize = xsize
        self.ysize = ysize
        self.zsize = zsize
        self.json_profile = json_profile
        self.can_print = can_print
        self.has_heated_platform = has_heated_platform
        self.number_of_tools = number_of_tools

    def get_info(self):
        return {
            "name": self.name,
            "driver_name": self.driver.name,
            "xsize": self.xsize,
            "ysize": self.ysize,
            "zsize": self.zsize,
            "can_print": self.can_print,
            "has_heated_platform": self.has_heated_platform,
            "number_of_tools": self.number_of_tools,
        }

    def get_gcode_scaffold(
            self, extruders, extruder_temperature, platform_temperature,
            material_name):
        raise NotImplementedError


class GcodeScaffold(object):
    def __init__(self):
        self.start = None
        self.end = None
        self.variables = None


# STATES:
    # DISCONNECTED: Machine is disconnected, and must be connected
    # IDLE: Machine is connected, but not doing anything
    # RUNNING: Machine is connected, and running some action
    # PAUSED: Machine is connected, but its current action is paused
    # UNAUTHENTICATED: Machine has been connected, but requires user
        # authentication for further use.
    # PENDING: Machine has been connected, but we are unsure of its status.
        # This is specifically used for USB Birdwing machines, where hotplug
        # events dont insinuate.
MachineState = conveyor.enum.enum(
    'MachineState', 'DISCONNECTED', 'IDLE', 'RUNNING', 'PAUSED',
    'UNAUTHENTICATED', 'PENDING')


MachineEvent = conveyor.enum.enum(
    'MachineEvent', 'CONNECT', 'DISCONNECT', 'DISCONNECTED', 'WENT_IDLE',
    'WENT_BUSY', 'START_OPERATION', 'PAUSE_OPERATION', 'UNPAUSE_OPERATION',
    'OPERATION_STOPPED',)


class Machine(object):
    def __init__(self, port, driver, profile, name=None):
        self._port = port
        # Name override, specifically for direct_connect
        if not name:
            self.name = self._port.machine_name
        else:
            self.name = name
        self._driver = driver
        self._profile = profile
        self._log = conveyor.log.getlogger(self)
        self._state = MachineState.DISCONNECTED
        self._state_condition = threading.Condition()
        self.state_changed = conveyor.event.Event('state_changed')
        self.temperature_changed = conveyor.event.Event('temperature_changed')

        # Used to pass Kaiten error notifications back to host-side clients
        self.error_notification_event = conveyor.event.Event(
            'error_notification')

        self.stack_error_notification_event = conveyor.event.Event(
            'stack_error_notification')

        # Used to pass Kaiten error acknowledgements back to host-side clients
        self.error_acknowledged_event = conveyor.event.Event(
            'error_acknowledged')

        # Used to notify host-side clients that the bot's network state has changed
        self.network_state_change_event = conveyor.event.Event(
            'network_state_changed')

    def get_info(self):
        profile = self.get_profile()

        # Base values used for both Printers and Digitizer
        dct = {
            'name': self.name,
            'driver_name': self.get_driver().name,
            'profile_name': profile.name,
            'state': self._state,
            'display_name': self.get_display_name(),
            'firmware_version': getattr(self, '_firmware_version', None)
        }

        # These are really just for printers, but sticking here for
        # now to avoid duplication in both s3g and birdwing. Could be
        # refactored more sensibly.
        if profile.json_profile:
            json = profile.json_profile.values

            has_heated_platform = (0 != len(json['heated_platforms']))
            platform_temperature = None
            if has_heated_platform:
                platform_temperature = getattr(
                    self, '_platform_temperature', None)

            dct.update({
                'toolhead_target_temperature': getattr(
                    self, "_toolhead_target_temperature", None),
                'printer_type': json['type'],
                'can_print': True,
                'has_heated_platform': has_heated_platform,
                'number_of_toolheads': len(json['tools']),
                'toolhead_temperature':
                    getattr(self, '_toolhead_temperature', None),
                'platform_temperature': platform_temperature,
                'build_volume': [json['axes']['X']['platform_length'],
                                 json['axes']['Y']['platform_length'],
                                 json['axes']['Z']['platform_length']]})
        return dct

    def is_authenticated(self):
        return self._state != conveyor.machine.MachineState.UNAUTHENTICATED

    def get_display_name(self):
        return self.get_port().display_name

    def get_firmware_version(self):
        return self._firmware_version

    def get_port(self):
        return self._port

    def set_port(self, port):
        self._port = port

    def get_driver(self):
        return self._driver

    def get_hash(self):
        return self.get_port().get_machine_hash()

    def get_profile(self):
        return self._profile

    def get_state(self):
        return self._state

    def is_idle(self):
        raise NotImplementedError

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def pause(self):
        raise NotImplementedError

    def unpause(self):
        raise NotImplementedError

    def cancel(self):
        raise NotImplementedError

    def print(
            self, input_path, extruders, extruder_temperature,
            platform_temperature, material_name, build_name, job):
        raise NotImplementedError

    def print_from_file(self, input_path, build_name, job):
        raise NotImplementedError

    # TODO: these are specific to S3G.

    def jog(self, axis, distance_mm, duration, job):
        raise NotImplementedError

    def reset_to_factory(self, job):
        raise NotImplementedError

    def upload_firmware(self, machine_type, pid, input_file, job):
        raise NotImplementedError

    def read_eeprom(self, job):
        raise NotImplementedError

    def write_eeprom(self, eeprom_map, job):
        raise NotImplementedError
