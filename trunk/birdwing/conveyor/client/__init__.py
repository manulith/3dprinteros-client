#vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/client/__init__.py
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

import itertools
import json
import logging
import os.path
import socket
import sys
import textwrap
import time

import conveyor.arg
import conveyor.job
import conveyor.jsonrpc
import conveyor.main
import conveyor.slicer
import conveyor.machine.port
import conveyor.main
import conveyor.job

from conveyor.decorator import args, command

class _ClientCommand(conveyor.main.Command):
    '''A client command.'''

    def _get_driver_name(self):
        if None is not self._parsed_args.driver_name:
            driver_name = self._parsed_args.driver_name
        else:
            driver_name = self._config.get('client', 'driver')
        return driver_name

    def _get_profile_name(self):
        if None is not self._parsed_args.profile_name:
            profile_name = self._parsed_args.profile_name
        else:
            profile_name = self._config.get('client', 'profile')
        return profile_name


class _JsonRpcCommand(_ClientCommand):
    '''
    A client command that requires a JSON-RPC connection to the conveyor
    service.

    '''

    def __init__(self, parsed_args, config):
        _ClientCommand.__init__(self, parsed_args, config)
        self._jsonrpc = None
        self._stop = False
        self._code = 0

    def run(self):
        address = self._config.get('common', 'address')
        try:
            self._connection = address.connect()
        except EnvironmentError as e:
            self._code = 1
            self._log.critical(
                'failed to connect to address: %s: %s',
                address, e.strerror, exc_info=True)
            if not self._pid_file_exists():
                self._log.critical(
                    'pid file missing; is the conveyor service running?')
        else:
            self._jsonrpc = conveyor.jsonrpc.JsonRpc(
                self._connection, self._connection)
            self._export_methods()
            hello_job = self._jsonrpc.request('hello', {"username": "conveyor"})
            hello_job.stoppedevent.attach(
                self._guard_callback(self._hello_callback))
            hello_job.start()
            self._jsonrpc.run()
        return self._code

    def _pid_file_exists(self):
        pid_file = self._config.get('common', 'pid_file')
        result = os.path.exists(pid_file)
        return result

    def _export_methods(self):
        '''
        Export JSON-RPC methods to the conveyor service. The default
        implementation does not export any methods.

        '''

    def _guard_callback(self, callback):
        '''
        Creates a new callback that invokes `_check_job` and then invokes
        `callback` only if `_check_job` returns `True`. This reduces some
        repetitive code.

        '''
        def guard(job):
            if self._check_job(job):
                def func():
                    try:
                        callback(job)
                    except Exception as e:
                        self._stop_jsonrpc()
                        raise
                conveyor.error.guard(self._log, func)
        return guard

    def _check_job(self, job):
        '''
        Returns whether or not a job ended successfully. It terminates the
        client if the job failed or was canceled.

        '''

        if conveyor.job.JobConclusion.ENDED == job.conclusion:
            result = True
        elif conveyor.job.JobConclusion.FAILED == job.conclusion:
            self._code = 1
            self._log.error('%s', job.failure)
            self._stop_jsonrpc()
            result = False
        elif conveyor.job.JobConclusion.CANCELED == job.conclusion:
            self._code = 1
            self._log.warning('canceled')
            self._stop_jsonrpc()
            result = False
        else:
            self._stop_jsonrpc()
            raise ValueError(job.conclusion)
        return result

    def _stop_jsonrpc(self):
        '''Stop the JSON-RPC connection. This will end the client.'''
        self._stop = True
        self._jsonrpc.stop()

    def _hello_callback(self, hello_job):
        '''
        A callback invoked after the command successfully invokes `hello` on
        the conveyor service. This callback can be used to invoke additional
        methods on the conveyor service.

        '''
        raise NotImplementedError


class _MethodCommand(_JsonRpcCommand):
    '''
    A client command that invokes a JSON-RPC request on the conveyor service.

    '''

    def _hello_callback(self, hello_job):
        method_job = self._create_method_job()
        method_job.stoppedevent.attach(
            self._guard_callback(self._method_callback))
        method_job.start()

    def _create_method_job(self):
        '''
        Creates a job for a request to be invoked on the conveyor service.

        '''

        raise NotImplementedError

    def _method_callback(self, method_job):
        '''
        A callback invoked when the request returns. This callback can be used
        to handle the result of the request, to handle errors, and to invoke
        additional methods on the conveyor service.

        '''
        raise NotImplementedError


class _QueryCommand(_MethodCommand):
    '''
    A client command that invokes a JSON-RPC request on the conveyor service
    and handles the result.

    '''

    def _method_callback(self, method_job):
        self._handle_result(method_job.result)
        self._stop_jsonrpc()

    def _handle_result(self, result):
        '''Handles the result of the query.'''
        raise NotImplementedError


@args(conveyor.arg.json)
class _JsonCommand(_QueryCommand):
    '''
    A client command that invokes a JSON-RPC request on the conveyor service
    and optionally prints the result in raw JSON format.

    '''

    def _handle_result(self, result):
        self._log.debug(result)
        if self._parsed_args.json:
            self._handle_result_json(result)
        else:
            self._handle_result_default(result)

    def _handle_result_json(self, result):
        '''
        Handles the result of the query by printing it in raw JSON format.

        '''
        json.dump(result, sys.stdout)

    def _handle_result_default(self, result):
        '''
        Handles the result of the query in some way other than printing it in
        raw JSON format.

        '''
        raise NotImplementedError


class _MonitorCommand(_MethodCommand):
    '''
    A client command that invokes a JSON-RPC request on the conveyor service
    and waits for a job to complete. The request must return a job id.

    '''

    def __init__(self, parsed_args, config):
        _MethodCommand.__init__(self, parsed_args, config)
        self._job_id = None
        self._expect_job = True

    def _export_methods(self):
        self._jsonrpc.addmethod('jobchanged', self._job_changed)

    def _job_changed(self, *args, **kwargs):
        '''
        Invoked by the conveyor service to inform the client that a job has
        changed.

        '''

        job = kwargs
        job_id = job["id"]
        if (not self._stop and None is not self._job_id
                and self._job_id == job_id):
            if conveyor.job.JobState.STOPPED == job["state"]:
                if conveyor.job.JobConclusion.ENDED == job["conclusion"]:
                    self._code = 0
                    self._log.info('job ended')
                elif conveyor.job.JobConclusion.FAILED == job["conclusion"]:
                    self._code = 1
                    self._log.error('job failed: %s', job["failure"])
                elif conveyor.job.JobConclusion.CANCELED == job["conclusion"]:
                    self._code = 1
                    self._log.warning('job canceled')
                else:
                    raise ValueError(job["conclusion"])
                self._stop_jsonrpc()

    def _method_callback(self, method_job):
        if (None is not method_job.result
                and isinstance(method_job.result, dict)
                and 'id' in method_job.result):
            self._job_id = method_job.result['id']
        elif self._expect_job:
            self._code = 1
            self._log.error(
                'the conveyor service returned invalid job information')
            self._stop_jsonrpc()
        else:
            try:
                self._handle_result(method_job.result)
            except Exception as e:
                pass
            self._stop_jsonrpc()

    def _handle_result(self, result):
        print("RESULT: %r" % (result))

@args(conveyor.arg.machine)
class _ConnectedCommand(_MonitorCommand):
    '''
    A client command that connects a machine, invokes a JSON-RPC request on the
    conveyor service and waits for a job to complete. The request must return a
    job id.

    This is essentially a `_MonitorCommand` that calls `connect` on the
    conveyor service before invoking the job-related method. `connect` must
    return a `MachineInfo` object with a `name` field. The machine's name is
    stored in an instance field called `_machine_name`.

    '''

    def __init__(self, parsed_args, config):
        _MonitorCommand.__init__(self, parsed_args, config)
        self._machine_name = None

    def _hello_callback(self, hello_job):
        # NOTE: this method doesn't use the `_get_driver_name` nor
        # `_get_profile_name` as the driver and profile can often be detected
        # automatically.
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        connect_job = self._jsonrpc.request('connect_to_machine', params)
        connect_job.stoppedevent.attach(
            self._guard_callback(self._connect_callback))
        connect_job.start()

    def _connect_callback(self, connect_job):
        self._machine_name = connect_job.result['name']
        method_job = self._create_method_job()
        method_job.stoppedevent.attach(
            self._guard_callback(self._method_callback))
        method_job.start()

class DebugCommand(_MethodCommand):
    name = 'debug'
    help = 'start the pdb debugger in the server.'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request("pdb_debug", params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.positional_layout_id)
@args(conveyor.arg.positional_access_token)
class StreamingPrintCommand(_ConnectedCommand):
    name = 'streaming_print'

    help = 'initiate a streaming print to Rep 2'

    def _create_method_job(self):
        params = {
            'machine_name' : self._machine_name,
            'layout_id' : self._parsed_args.layout_id,
            'access_token' : self._parsed_args.access_token,
            }
        method_job = self._jsonrpc.request('streaming_print', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.positional_job)
class JobResumeCommand(_MethodCommand):
    name = 'jobresume'

    help = 'resumes a job'

    def _create_method_job(self):
        params = {'id': self._parsed_args.job_id}
        method_job = self._jsonrpc.request('job_resume', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.positional_job)
class JobPauseCommand(_MethodCommand):
    name = 'jobpause'

    help = 'pauses a job'

    def _create_method_job(self):
        params = {'id': self._parsed_args.job_id}
        method_job = self._jsonrpc.request('job_pause', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.positional_job)
class CancelCommand(_MethodCommand):
    name = 'cancel'

    help = 'cancel a job'

    def _create_method_job(self):
        params = {'id': self._parsed_args.job_id}
        method_job = self._jsonrpc.request('job_cancel', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.machine)
@args(conveyor.arg.username)
class BirdWingLockCommand(_QueryCommand):
    name = "birdwinglock"
    help = "Lock a birdwing machine for a specific user"

    def _create_method_job(self):
        params = {
            "username": self._parsed_args.username,
            'machine_name': self._parsed_args.machine_name,
        }
        method_job = self._jsonrpc.request('birdwinglock', params)
        return method_job

    def _handle_result(self, result):
        print(result)
            
@args(conveyor.arg.machine)
@args(conveyor.arg.username)
class BirdWingUnlockCommand(_QueryCommand):
    name = "birdwingunlock"
    help = "Unlock a birdwing machine for a specific user"

    def _create_method_job(self):
        params = {
            "username": self._parsed_args.username,
            'machine_name': self._parsed_args.machine_name,
        }
        method_job = self._jsonrpc.request('birdwingunlock', params)
        return method_job

    def _handle_result(self, result):
        print(result)


@args(conveyor.arg.machine)
class BirdWingCancelCommand(_QueryCommand):
    name = "birdwingcancel"

    help = "Cancel the current process running on the BoardWing board"

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        method_job = self._jsonrpc.request('birdwingcancel', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.machine)
@args(conveyor.arg.filepath)
class BirdWingUpdateFirmwareCommand(_QueryCommand):
    name = 'birdwingupdatefirmware'
    help = 'Send firmware file to machine and update its firmware'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'firmware_path': self._parsed_args.filepath,
        }
        method_job = self._jsonrpc.request('birdwingupdatefirmware', params)
        return method_job

@args(conveyor.arg.ip_address)
class DirectConnectCommand(_QueryCommand):
    name = "direct_connect"
    help = "Directly connect to a machine you cannot see via UDP multicast"

    def _create_method_job(self):
        params = {
            'ip_address': self._parsed_args.ip_address,
        }
        method_job = self._jsonrpc.request("direct_connect", params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.positional_input_file)
@args(conveyor.arg.machine)
class BirdWingListCommand(_QueryCommand):
    name = 'birdwinglist'
    help = 'List all logs for the birdwing board'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'directory': self._parsed_args.input_file,
        }
        method_job = self._jsonrpc.request('birdwinglist', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.positional_input_file)
@args(conveyor.arg.positional_output_file)
@args(conveyor.arg.machine)
class BirdWingGetCommand(_QueryCommand):
    name = 'birdwingget'
    help = 'get a file from the birdwing board'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'localpath': os.path.abspath(self._parsed_args.input_file),
            'remotepath': self._parsed_args.output_file,
        }
        method_job = self._jsonrpc.request('birdwingget', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.positional_input_file)
@args(conveyor.arg.positional_output_file)
@args(conveyor.arg.machine)
class BirdWingPutCommand(_QueryCommand):
    name = 'birdwingput'
    help = 'put a file to the birdwing board'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'localpath': os.path.abspath(self._parsed_args.input_file),
            'remotepath': self._parsed_args.output_file,
        }
        method_job = self._jsonrpc.request('birdwingput', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.host_version)
@args(conveyor.arg.machine)
class BirdWingHandshakeCommand(_QueryCommand):
    name = 'birdwinghandshake'
    help = 'determine if we can communicate with the birdwing board'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'host_version': self._parsed_args.host_version,
        }
        method_job = self._jsonrpc.request('birdwinghandshake', params)
        return method_job

    def _handle_result(self, result):
        print("I can%s talk to this Embedded Conveyor!" % ('not' if not result else ''))

@args(conveyor.arg.machine)
@args(conveyor.arg.positional_output_file)
class BirdWingZipLogsCommand(_QueryCommand):
    name = 'birdwingziplogs'
    help = 'create a .zip on birdwing side containing all its logs'
    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'zip_path': self._parsed_args.output_file,
        }
        method_job = self._jsonrpc.request('birdwingziplogs', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.username)
@args(conveyor.arg.thingiverse_token)
@args(conveyor.arg.birdwing_code)
@args(conveyor.arg.client_secret)
class SendThingiverseCredentialsCommand(_ConnectedCommand):
    name = 'send_thingiverse_credentials'
    help = 'Sends thingiverse credentials to the birdwing machine'

    def _create_method_job(self):
        self._expect_job = False
        params = {
            "machine_name": self._machine_name,
            "username": self._parsed_args.username,
            "thingiverse_token": self._parsed_args.thingiverse_token,
            "birdwing_code": self._parsed_args.birdwing_code,
            "client_secret": self._parsed_args.client_secret,
        }
        task = self._jsonrpc.request("send_thingiverse_credentials", params)
        return task

    def _handle_result(self, result):
        print(result)
            

@args(conveyor.arg.client_secret)
@args(conveyor.arg.username)
@args(conveyor.arg.thingiverse_token)
class GetAuthenticationCodeCommand(_ConnectedCommand):
    name = 'get_authentication_code'

    help = 'do an initial pairing with a birdwing machine'

    def _create_method_job(self):
        self._expect_job = False
        params = {
            "machine_name": self._machine_name,
            "username": self._parsed_args.username,
            "client_secret": self._parsed_args.client_secret,
            "thingiverse_token": self._parsed_args.thingiverse_token,
        }
        task = self._jsonrpc.request("get_authentication_code", params)
        return task

    def _handle_result(self, result):
        print("The Birdwing secret is: %r" % (result))

@args(conveyor.arg.client_secret)
@args(conveyor.arg.birdwing_code)
class AuthenticateConnectionCommand(_ConnectedCommand):
    name = 'authenticate_connection'
    help = "authenticate a machine's connection"

    def _create_method_job(self):
        self._expect_job = False
        params = {
            'machine_name': self._machine_name,
            "client_secret": self._parsed_args.client_secret,
            'birdwing_code': self._parsed_args.birdwing_code,
        }
        task = self._jsonrpc.request("authenticate_connection", params)
        return task

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.display_name)
class ChangeDisplayNameCommand(_ConnectedCommand):
    name = "change_display_name"
    help = "change a machine's display name"

    def _create_method_job(self):
        self._expect_job = False
        params = {
            "machine_name": self._machine_name,
            "new_display_name": self._parsed_args.display_name,
        }
        task = self._jsonrpc.request("change_display_name", params)
        return task

    def _handle_result(self, result):
        pass


@args(conveyor.arg.machine)
class ConnectCommand(_MethodCommand):
    name = 'connect'

    help = 'connect to a machine'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,}
        method_job = self._jsonrpc.request('connect_to_machine', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.positional_output_file_optional)
class DefaultConfigCommand(_ClientCommand):
    name = 'defaultconfig'

    help = 'print the platform\'s default conveyor configuration'

    def run(self):
        if None is self._parsed_args.output_file:
            conveyor.config.format_default(sys.stdout)
        else:
            with open(self._parsed_args.output_file, 'w') as fp:
                conveyor.config.format_default(fp)
        return 0



@args(conveyor.arg.machine)
class DisconnectCommand(_MethodCommand):
    name = 'disconnect'

    help = 'disconnect from a machine'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        method_job = self._jsonrpc.request('disconnect', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.driver)
@args(conveyor.arg.machine_type)
@args(conveyor.arg.firmware_version)
@args(conveyor.arg.pid)
class DownloadFirmware(_QueryCommand):
    name = 'downloadfirmware'

    help = 'download firmware'

    def _create_method_job(self):
        params = {
            'driver_name': self._get_driver_name(),
            'machine_type': self._parsed_args.machine_type,
            'pid': self._parsed_args.pid,
            'firmware_version': self._parsed_args.firmware_version,
        }
        method_job = self._jsonrpc.request('downloadfirmware', params)
        return method_job

    def _handle_result(self, result):
        self._log.info('firmware downloaded to: %s', result)


@args(conveyor.arg.positional_driver)
class DriverCommand(_JsonCommand):
    name = 'driver'

    help = 'get the details for a driver'

    def _create_method_job(self):
        params = {'driver_name': self._get_driver_name(),}
        method_job = self._jsonrpc.request('get_driver', params)
        return method_job

    def _handle_result_default(self, result):
        driver = result
        drivers = [driver]
        _print_driver_profiles(self._log, drivers)


class DriversCommand(_JsonCommand):
    name = 'drivers'

    help = 'list the available drivers'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request('get_drivers', params)
        return method_job

    def _handle_result_default(self, result):
        drivers = result
        _print_driver_profiles(self._log, drivers)


@args(conveyor.arg.driver)
@args(conveyor.arg.machine_type)
class GetMachineVersions(_QueryCommand):
    name = 'getmachineversions'

    help = 'get the firmware versions available for a machine'

    def _create_method_job(self):
        params = {
            'driver_name': self._get_driver_name(),
            'machine_type': self._parsed_args.machine_type,
        }
        method_job = self._jsonrpc.request('getmachineversions', params)
        return method_job

    def _handle_result(self, result):
        self._log.info('%s', result)


class DirCommand(_QueryCommand):
    name = 'dir'

    help = 'list the methods available from the conveyor service'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request('dir', params)
        return method_job

    def _handle_result(self, result):
        for val in result:
            print("Conveyor Function:")
            print(val)
            print("\n\n")


@args(conveyor.arg.driver)
class GetUploadableMachines(_QueryCommand):
    name = 'getuploadablemachines'

    help = 'list the machines to which conveyor can upload firmware'

    def _create_method_job(self):
        params = {'driver_name': self._get_driver_name(),}
        method_job = self._jsonrpc.request('getuploadablemachines', params)
        return method_job

    def _handle_result(self, result):
        print(result)


@args(conveyor.arg.positional_job)
class JobCommand(_JsonCommand):
    name = 'job'

    help = 'get the details for a job'

    def _create_method_job(self):
        params = {'id': int(self._parsed_args.job_id)}
        method_job = self._jsonrpc.request('getjob', params)
        return method_job

    def _handle_result_default(self, result):
        self._log.info('%s', result)


class JobsCommand(_JsonCommand):
    name = 'jobs'

    help = 'get the details for all jobs'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request('getjobs', params)
        return method_job

    def _handle_result_default(self, result):
        self._log.info('%s', result)


class PauseCommand(_ConnectedCommand):
    name = 'pause'

    help = 'pause a machine'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        pause_job = self._jsonrpc.request('pause', params)
        return pause_job


class PortsCommand(_JsonCommand):
    name = 'ports'

    help = 'list the available ports'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request('getports', params)
        return method_job

    def _handle_result_default(self, result):
        for port in result:
            self._handle_serial(port)

    def _handle_serial(self, port):
        self._log.info('Serial port:')
        self._log.info('  machine_type   - %s', port['machine_type'])
        self._log.info('  iSerial - %s', port["machine_name"]['iserial'])
        self._log.info('  VID:PID - %04X:%04X', port["machine_name"]['vid'], port["machine_name"]['pid'])

@args(conveyor.arg.machine)
@args(conveyor.arg.positional_axis)
@args(conveyor.arg.positional_distance)
@args(conveyor.arg.positional_duration)
class JogCommand(_MethodCommand):
    name = 'jog'
    help = 'jog'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'axis': self._parsed_args.axis,
            'distance_mm': self._parsed_args.distance_mm,
            'duration': self._parsed_args.duration
        }
        method_job = self._jsonrpc.request('jog', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.machine)
class TOMCalibrationCommand(_MethodCommand):
    name = 'tomcalibration'
    help = 'calibrates TOMs home offsets'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('tom_calibration', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.machine)
class HomeCommand(_MethodCommand):
    name = 'home'
    help = 'homes the XYZ axes'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('home', params)
        return method_job
    def _method_callback(self, method_job):
        self._stop_jsonrpc()

class FirstContactCommand(_ConnectedCommand):
    name = 'first_contact'
    help = 'Mark this printer as having make first contact with makerware'

    def _create_method_job(self):
        self._expect_job = False
        params = {
            "machine_name": self._machine_name}
        method_job = self._jsonrpc.request("first_contact", params)
        return method_job

@args(conveyor.arg.machine)
class NetworkStateCommand(_QueryCommand):
    name = 'networkstate'
    help = 'Get state of network'

    def __init__(self, parsed_args, config):
        _QueryCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('network_state', params)
        return method_job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.machine)
class WifiScanCommand(_QueryCommand):
    name = 'wifiscan'
    help = 'Scan for wifi networks'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('wifi_scan', params)
        return method_job

    def _handle_result(self, result):
        for res in result:
          print(res)

@args(conveyor.arg.wifi_path)
@args(conveyor.arg.wifi_password)
class WifiConnectCommand(_ConnectedCommand):
    name = 'wificonnect'
    help = 'Connect to a wifi network'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'path': self._parsed_args.wifi_path,
            'password': self._parsed_args.wifi_password
        }
        method_job = self._jsonrpc.request('wifi_connect', params)
        return method_job

class WifiDisconnectCommand(_ConnectedCommand):
    name = 'wifidisconnect'
    help = 'Disconnect from a wifi network'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        method_job = self._jsonrpc.request('wifi_disconnect', params)
        return method_job

@args(conveyor.arg.wifi_path)
class WifiForgetCommand(_ConnectedCommand):
    name = 'wififorget'
    help = 'Forget a wifi network'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'path': self._parsed_args.wifi_path,
        }
        method_job = self._jsonrpc.request('wifi_forget', params)
        return method_job

class WifiDisableCommand(_ConnectedCommand):
    name = 'wifidisable'
    help = 'Disable wifi on a bot'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('wifi_disable', params)
        return method_job

class WifiEnableCommand(_ConnectedCommand):
    name = 'wifienable'
    help = 'Enable wifi on a bot'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        method_job = self._jsonrpc.request('wifi_enable', params)
        return method_job

class PrintAgainCommand(_ConnectedCommand):
    name = 'print_again'
    help = "Print the file you just printed to this brirdwing machine again"

    def _create_method_job(self):
        params = {
            "machine_name": self._machine_name}
        method_job = self._jsonrpc.request("print_again", params)
        return method_job

@args(conveyor.arg.extruder)
@args(conveyor.arg.has_start_end)
@args(conveyor.arg.heat_platform)
@args(conveyor.arg.slicer)
@args(conveyor.arg.slicer_settings)
@args(conveyor.arg.metadata)
@args(conveyor.arg.thumbnail_dir)
@args(conveyor.arg.positional_input_file)
class PrintCommand(_ConnectedCommand):
    name = 'print'

    help = 'print an object'

    def _create_method_job(self):
        import json
        slicer_settings = _create_slicer_settings(
            self._parsed_args, self._config)
        params = {
            'machine_name': self._machine_name,
            'input_file': os.path.abspath(self._parsed_args.input_file),
            'has_start_end': self._parsed_args.has_start_end,
            'slicer_settings': slicer_settings,
            'metadata': json.loads(self._parsed_args.metadata),
            'thumbnail_dir': self._parsed_args.thumbnail_dir,
        }
        method_job = self._jsonrpc.request('print', params)
        return method_job

@args(conveyor.arg.positional_input_file)
class PrintFromFileCommand(_ConnectedCommand):
    name = 'printfromfile'
    help = 'print a presliced file'

    def _create_method_job(self):
        params = {
            'machine_name': self._machine_name,
            'input_file': os.path.abspath(self._parsed_args.input_file),
        }
        method_job = self._jsonrpc.request('print_from_file', params)
        return method_job


@args(conveyor.arg.extruder)
@args(conveyor.arg.has_start_end)
@args(conveyor.arg.heat_platform)
@args(conveyor.arg.profile)
@args(conveyor.arg.slicer)
@args(conveyor.arg.slicer_settings)
@args(conveyor.arg.metadata)
@args(conveyor.arg.thumbnail_dir)
@args(conveyor.arg.positional_input_file)
@args(conveyor.arg.positional_output_file)
class PrintToFileCommand(_MonitorCommand):
    name = 'printtofile'

    help = 'print an object to an .s3g or .x3g file'

    def _create_method_job(self):
        import json
        slicer_settings = _create_slicer_settings(
            self._parsed_args, self._config)
        params = {
            'profile_name': self._get_profile_name(),
            'input_file': os.path.abspath(self._parsed_args.input_file),
            'output_file': os.path.abspath(self._parsed_args.output_file),
            'has_start_end': self._parsed_args.has_start_end,
            'slicer_settings': slicer_settings,
            'metadata': json.loads(self._parsed_args.metadata),
            'thumbnail_dir': self._parsed_args.thumbnail_dir,
        }
        method_job = self._jsonrpc.request('print_to_file', params)
        return method_job


class PrintersCommand(_JsonCommand):
    name = 'printers'

    help = 'list connected printers'

    def _create_method_job(self):
        params = {}
        method_job = self._jsonrpc.request('getprinters', params)
        return method_job

    def _handle_result_default(self, result):
        for machine in result:
            self._log.info('Printer:')
            self._log.info('  name        - %s', machine['name'])
            self._log.info('  state       - %s', machine['state'])
            try:
                self._log.info('  temperature - %s', machine['temperature'])
            except Exception:
                pass
            self._log.info('  firmware    - %s', machine['firmware_version'])
            self._log.info('  displayname - %s', machine['display_name'])

            # TODO: stop being lazy and add the rest of the fields.


@args(conveyor.arg.positional_driver)
@args(conveyor.arg.positional_profile)
class ProfileCommand(_JsonCommand):
    name = 'profile'

    help = 'get the details for a profile'

    def _create_method_job(self):
        params = {
            'driver_name': self._get_driver_name(),
            'profile_name': self._get_profile_name(),
        }
        method_job = self._jsonrpc.request('get_profile', params)
        return method_job

    def _handle_result_default(self, result):
        profile = result
        profiles = [profile]
        driver = {
            'name': self._parsed_args.driver_name,
            'profiles': profiles,
        }
        drivers = [driver]
        _print_driver_profiles(self._log, drivers)


@args(conveyor.arg.positional_driver)
class ProfilesCommand(_JsonCommand):
    name = 'profiles'

    help = 'list the available profiles'

    def _create_method_job(self):
        params = {'driver_name': self._get_driver_name(),}
        method_job = self._jsonrpc.request('get_profiles', params)
        return method_job

    def _handle_result_default(self, result):
        profiles = result
        driver = {
            'name': self._parsed_args.driver_name,
            'profiles': profiles,
        }
        drivers = [driver]
        _print_driver_profiles(self._log, drivers)


@args(conveyor.arg.machine)
@args(conveyor.arg.positional_output_file)
class ReadEepromCommand(_QueryCommand):
    name = 'readeeprom'

    help = 'read a machine EEPROM'

    def _create_method_job(self):
        params = {'printername': self._parsed_args.machine_name}
        method_job = self._jsonrpc.request('readeeprom', params)
        return method_job

    def _handle_result(self, result):
        output_file = os.path.abspath(self._parsed_args.output_file)
        with open(output_file, 'w') as fp:
            json.dump(result, fp, sort_keys=True, indent=2)

@args(conveyor.arg.machine)
class ResetToFactoryCommand(_QueryCommand):
    name = 'resettofactory'

    help = 'reset a machine EEPROM to factory settings'

    def _create_method_job(self):
        params = {'machine_name': self._parsed_args.machine_name}
        method_job = self._jsonrpc.request('resettofactory', params)
        return method_job

    def _handle_result(self, result):
        pass

@args(conveyor.arg.machine)
class ResetEepromCompletelyCommand(_MethodCommand):
    name = 'reseteepromcompletely'

    help = 'reset all bytes in EEPROM to "0xFF", the default state for the EEPROM'

    def _create_method_job(self):
        params = {'machine_name': self._parsed_args.machine_name}
        method_job = self._jsonrpc.request('reseteepromcompletely', params)
        return method_job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.add_start_end)
@args(conveyor.arg.extruder)
@args(conveyor.arg.heat_platform)
@args(conveyor.arg.profile)
@args(conveyor.arg.slicer)
@args(conveyor.arg.slicer_settings)
@args(conveyor.arg.positional_input_file)
@args(conveyor.arg.positional_output_file)
class SliceCommand(_MonitorCommand):
    name = 'slice'

    help = 'slice an object to a .gcode file'

    def _create_method_job(self):
        slicer_settings = _create_slicer_settings(
            self._parsed_args, self._config)
        params = {
            'profile_name': self._get_profile_name(),
            'input_file': os.path.abspath(self._parsed_args.input_file),
            'output_file': os.path.abspath(self._parsed_args.output_file),
            'add_start_end': self._parsed_args.add_start_end,
            'slicer_settings': slicer_settings,
        }
        method_job = self._jsonrpc.request('slice', params)
        return method_job


class UnpauseCommand(_ConnectedCommand):
    name = 'unpause'

    help = 'unpause a machine'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'driver_name': self._get_driver_name(),
            'profile_name': self._get_profile_name(),
        }
        pause_job = self._jsonrpc.request('unpause', params)
        return pause_job

@args(conveyor.arg.positional_input_file)
class UpgradeMiracleGrueConfigCommand(_QueryCommand):
    name = 'upgrademiraclegrueconfig'
    help = 'Upgrades the miracle grue config and writes it out to *.config.upgrade'

    def _create_method_job(self):
        with open(os.path.abspath(self._parsed_args.input_file)) as f:
            json_config = json.load(f)
        params = {
            'config': json_config,
        }
        upgrade_job = self._jsonrpc.request('upgrade_miracle_grue_config', params)
        return upgrade_job

    def _handle_result(self, result):
        with open("%s.upgrade" % (os.path.abspath(self._parsed_args.input_file)), 'w') as f:
            json.dump(result, f)

@args(conveyor.arg.positional_input_file)
class StartUploadFirmwareJobCommand(_ConnectedCommand):
    name = 'start_upload_firmware_job'

    help = 'start upload firmware job'

    def _create_method_job(self):
        self._expect_job = False
        params = {
            'machine_name': self._parsed_args.machine_name,
            'filename': os.path.abspath(self._parsed_args.input_file),
        }
        method_job = self._jsonrpc.request('start_upload_firmware_job', params)
        return method_job

    def _handle_result(self, result):
        print(result)


@args(conveyor.arg.positional_input_file)
class UploadFirmwareCommand(_ConnectedCommand):
    name = 'upload_firmware'

    help = 'upload firmware'

    def _create_method_job(self):
        self._expect_job = False
        params = {
            'machine_name': self._parsed_args.machine_name,
            'filename': os.path.abspath(self._parsed_args.input_file),
        }
        method_job = self._jsonrpc.request('uploadfirmware', params)
        return method_job

    def _handle_result(self, result):
        pass


class WaitForServiceCommand(_ClientCommand):
    name = 'waitforservice'

    help = 'wait for the conveyor service to start'

    def run(self):
        now = time.time()
        failtime = now + 30.0
        address = self._config.get('common', 'address')
        while True:
            try:
                address.connect()
            except:
                now = time.time()
                if now < failtime:
                    time.sleep(1.0)
                else:
                    self._log.error('failed to connect to conveyor service')
                    code = 1
                    break
            else:
                self._log.info('connected')
                code = 0
                break
        return code


@args(conveyor.arg.positional_input_file)
class WriteEepromCommand(_QueryCommand):
    name = 'writeeeprom'

    help = 'write a machine EEPROM'

    def _create_method_job(self):
        input_file = os.path.abspath(self._parsed_args.input_file)
        with open(input_file) as fp:
            eeprommap = json.load(fp)
        params = {
            'printername': None,
            'eeprommap': eeprommap,
        }
        method_job = self._jsonrpc.request('writeeeprommap', params)
        return method_job

    def _handle_result(self, result):
        pass

####### Scanner Functions #######
@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.mesh_id)
@args(conveyor.arg.input_path)
@args(conveyor.arg.positional_output_file)
class GlobalAlignAndMeshCommand(_QueryCommand):
    name = 'globalalignandmesh'
    help = 'Global align and mesh point clouds'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'mesh_id': self._parsed_args.mesh_id,
            'input_path': self._parsed_args.input_path,
            'output_file': self._parsed_args.output_file,
        }            
        job = self._jsonrpc.request('global_align_and_mesh', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.machine)
class GetReprojectionErrorCommand(_QueryCommand):
    name = "getreprojectionerror"

    help = "Get the reprojection error for this machine"

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('getreprojectionerror', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.input_files)
@args(conveyor.arg.sample_rate)
@args(conveyor.arg.max_samples)
@args(conveyor.arg.inlier_ratio)
@args(conveyor.arg.max_iterations)
class PointCloudGlobalAlignmentCommand(_QueryCommand):
    name = 'pointcloudglobalalignment'
    help = 'Global alignment of multiple point clouds'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'input_files': self._parsed_args.input_files,
            'sample_rate': self._parsed_args.sample_rate,
            'max_samples': self._parsed_args.max_samples,
            'inlier_ratio': self._parsed_args.inlier_ratio,
            'max_iterations': self._parsed_args.max_iterations,
        }            
        job = self._jsonrpc.request('point_cloud_global_alignment', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.side)
@args(conveyor.arg.bounding_cylinder_top)
@args(conveyor.arg.bounding_cylinder_bottom)
@args(conveyor.arg.bounding_cylinder_radius)
class PointCloudCropCommand(_QueryCommand):
    name = 'pointcloudcrop'
    help = 'Crop a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'side': self._parsed_args.side,
            'bounding_cylinder_top': self._parsed_args.bounding_cylinder_top,
            'bounding_cylinder_bottom': self._parsed_args.bounding_cylinder_bottom,
            'bounding_cylinder_radius': self._parsed_args.bounding_cylinder_radius,
        }             
        job = self._jsonrpc.request('point_cloud_crop', params)
        return job 
                 
    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.grid_size)
@args(conveyor.arg.nearest_neighbors)
@args(conveyor.arg.adaptive_sigma)
@args(conveyor.arg.smoothing_nearest_neighbors)
@args(conveyor.arg.smoothing_iterations)
@args(conveyor.arg.fixed_cutoff_percent)
@args(conveyor.arg.remove_outliers)
class PointCloudProcessCommand(_QueryCommand):
    name = 'pointcloudprocess'
    help = 'Process a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'grid_size': self._parsed_args.grid_size,
            'nearest_neighbors': self._parsed_args.nearest_neighbors,
            'adaptive_sigma': self._parsed_args.adaptive_sigma,
            'smoothing_nearest_neighbors': self._parsed_args.smoothing_nearest_neighbors,
            'smoothing_iterations': self._parsed_args.smoothing_iterations,
            'fixed_cutoff_percent': self._parsed_args.fixed_cutoff_percent,
            'remove_outliers': self._parsed_args.remove_outliers,
        }
        job = self._jsonrpc.request('point_cloud_process', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
class PointCloudCoarseAlignmentCommand(_QueryCommand):
    name = 'pointcloudcoarsealignment'
    help = 'Coarse alignment of a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id
        }
        job = self._jsonrpc.request('point_cloud_coarse_alignment', params)
        return job

    def _handle_result(self, result):
        print(result)


@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.sample_rate)
@args(conveyor.arg.max_samples)
@args(conveyor.arg.inlier_ratio)
@args(conveyor.arg.max_iterations)
class PointCloudFineAlignmentCommand(_QueryCommand):
    name = 'pointcloudfinealignment'
    help = 'Fine alignment of a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'sample_rate': self._parsed_args.sample_rate,
            'max_samples': self._parsed_args.max_samples,
            'inlier_ratio': self._parsed_args.inlier_ratio,
            'max_iterations': self._parsed_args.max_iterations,
        }
        job = self._jsonrpc.request('point_cloud_fine_alignment', params)
        return job

    def _handle_result(self, result):
        print(result)

class PointCloudCreateCommand(_QueryCommand):
    name = 'pointcloudcreate'
    help = 'Create a point cloud for scanning'

    def _create_method_job(self):
        params = {}
        job = self._jsonrpc.request('point_cloud_create', params)
        return job

    def _handle_result(self, result):
        print("Point Cloud Id: %i" % (result))

@args(conveyor.arg.point_cloud_id)
class PointCloudDestroyCommand(_QueryCommand):
    name = 'pointclouddestroy'
    help = 'Destroy a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
        }
        job = self._jsonrpc.request('point_cloud_destroy', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.positional_output_file)
class PointCloudSaveCommand(_QueryCommand):
    name = 'pointcloudsave'
    help = 'Save a point cloud'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'output_path': os.path.abspath(self._parsed_args.output_file),
        }
        job = self._jsonrpc.request('point_cloud_save', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.side)
@args(conveyor.arg.positional_input_file)
class PointCloudLoadCommand(_QueryCommand):
    name = 'pointcloudload'
    help = 'Loads a point cloud from a file'

    def _create_method_job(self):
        params = {
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'side': self._parsed_args.side,
            'input_file': os.path.abspath(self._parsed_args.input_file),
        }
        job = self._jsonrpc.request('point_cloud_load', params)
        return job

    def _handle_result(self, result):
        return result

@args(conveyor.arg.src_id)
@args(conveyor.arg.src_side)
@args(conveyor.arg.dst_id)
@args(conveyor.arg.dst_side)
class PointCloudLoadFromIDCommand(_QueryCommand):
    name = 'pointcloudloadfromid'
    help = 'Copies point cloud from src ID to dst ID'

    def _create_method_job(self):
        params = {
            'src_id': self._parsed_args.src_id,
            'src_side': self._parsed_args.src_side,
            'dst_id': self._parsed_args.dst_id,
            'dst_side': self._parsed_args.dst_side,
        }
        job = self._jsonrpc.request('point_cloud_load_from_id', params)
        return job

    def _handle_result(self, result):
        return result

@args(conveyor.arg.archive_images)
@args(conveyor.arg.no_archive_images)
@args(conveyor.arg.archive_path)
class CalibrateCameraCommand(_ConnectedCommand):
    name = "calibratecamera"
    help = "Calibrate camera"

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'archive': self._parsed_args.archive_images,
        }
        if self._parsed_args.archive_path:
            params['archive_path'] = os.path.abspath(
                self._parsed_args.archive_path)
        else:
            params['archive_path'] = self._parsed_args.archive_path

        job = self._jsonrpc.request('create_calibrate_camera_job', params)
        return job

@args(conveyor.arg.archive_images)
@args(conveyor.arg.no_archive_images)
@args(conveyor.arg.archive_path)
class CalibrateTurntableCommand(_ConnectedCommand):
    name = "calibrateturntable"
    help = "Calibrate turntable"

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'archive': self._parsed_args.archive_images,
        }
        if self._parsed_args.archive_path:
            params['archive_path'] = os.path.abspath(
                self._parsed_args.archive_path)
        else:
            params['archive_path'] = self._parsed_args.archive_path
        job = self._jsonrpc.request('create_calibrate_turntable_job', params)
        return job

@args(conveyor.arg.point_cloud_id)
@args(conveyor.arg.rotation_resolution)
@args(conveyor.arg.exposure)
@args(conveyor.arg.intensity_threshold)
@args(conveyor.arg.laserline_peak)
@args(conveyor.arg.laser)
@args(conveyor.arg.archive_mesh)
@args(conveyor.arg.no_archive_mesh)
@args(conveyor.arg.archive_point_clouds)
@args(conveyor.arg.no_archive_point_clouds)
@args(conveyor.arg.bounding_cylinder_top)
@args(conveyor.arg.bounding_cylinder_bottom)
@args(conveyor.arg.bounding_cylinder_radius)
@args(conveyor.arg.archive_path)
class ScanCommand(_ConnectedCommand):
    name = "scan"
    help = "Scan an object"

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'point_cloud_id': self._parsed_args.point_cloud_id,
            'rotation_resolution': self._parsed_args.rotation_resolution,
            'exposure': self._parsed_args.exposure,
            'intensity_threshold': self._parsed_args.intensity_threshold,
            'laserline_peak': self._parsed_args.laserline_peak,
            'laser': self._parsed_args.laser,
            'archive_mesh': self._parsed_args.archive_mesh,
            'archive_point_clouds': self._parsed_args.archive_point_clouds,
            'bounding_cylinder_top': self._parsed_args.bounding_cylinder_top,
            'bounding_cylinder_bottom': self._parsed_args.bounding_cylinder_bottom,
            'bounding_cylinder_radius': self._parsed_args.bounding_cylinder_radius,
        }
        if self._parsed_args.archive_path:
            params['archive_path'] = os.path.abspath(
                self._parsed_args.archive_path)
        else:
            params['archive_path'] = self._parsed_args.archive_path
        job = self._jsonrpc.request('scan', params)
        return job


@args(conveyor.arg.steps)
@args(conveyor.arg.rotation_resolution)
class ScannerJogCommand(_ConnectedCommand):
    name = 'scannerjog'

    help = 'Jog a Digitizer Scanner'

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'steps': self._parsed_args.steps,
            'rotation_resolution': self._parsed_args.rotation_resolution,
        }
        job = self._jsonrpc.request('scannerjog', params)
        return job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()


@args(conveyor.arg.min_octree_depth)
@args(conveyor.arg.max_octree_depth)
@args(conveyor.arg.solver_divide)
@args(conveyor.arg.iso_divide)
@args(conveyor.arg.min_samples)
@args(conveyor.arg.scale)
@args(conveyor.arg.manifold)
@args(conveyor.arg.no_manifold)
@args(conveyor.arg.mesh_id)
@args(conveyor.arg.point_cloud_id)
class MeshCommand(_QueryCommand):
    name = 'mesh'
    help = 'Turn a pointcloud into an stl.'

    def _create_method_job(self):
        params = {
            "min_octree_depth": self._parsed_args.min_octree_depth,
            "max_octree_depth": self._parsed_args.max_octree_depth,
            "solver_divide": self._parsed_args.solver_divide,
            "iso_divide": self._parsed_args.iso_divide,
            "min_samples": self._parsed_args.min_samples,
            "scale": self._parsed_args.scale,
            "manifold": self._parsed_args.manifold,
            'mesh_id': self._parsed_args.mesh_id,
            'point_cloud_id': self._parsed_args.point_cloud_id
        }
        job = self._jsonrpc.request("mesh_reconstruct_point_cloud", params)
        return job

    def _handle_result(self, result):
        print(result)

class QueryDigitizerCommand(_ConnectedCommand):
    name = 'querydigitizer'
    help = 'Ask a digitizer about its state'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('querydigitizer', params)
        return job

@args(conveyor.arg.machine)
@args(conveyor.arg.calibration_images)
class CalibrateCameraOldCommand(_QueryCommand):
    name = 'calibratecameraold'
    help = 'Old calibrate the camera of a digitizer'

    def __init__(self, parsed_args, config):
        _QueryCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'calibration_images': self._parsed_args.calibration_images
        }
        job = self._jsonrpc.request('calibratecamera', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.calibration_images)
@args(conveyor.arg.laser_calibration_images)
@args(conveyor.arg.laser)
class CalibrateLaserCommand(_ConnectedCommand):
    name = 'calibratelaser'
    help = 'Calibrate the laser of a digitizer'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'calibration_images': self._parsed_args.calibration_images,
            'laser_images': self._parsed_args.laser_calibration_images,
            'laser': self._parsed_args.laser,
        }
        job = self._jsonrpc.request('calibratelaser', params)
        return job

@args(conveyor.arg.machine)
class CalibrateTurntableOldCommand(_QueryCommand):
    name = 'calibrateturntableold'
    help = 'Old calibrate the platform of a digitizer'

    def __init__(self, parsed_args, config):
        _QueryCommand.__init__(self, parsed_args, config)

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name
        }
        job = self._jsonrpc.request('calibrateturntable', params)
        return job

    def _handle_result(self, result):
        print(result)

@args(conveyor.arg.positional_output_file)
class SaveCalibrationCommand(_ConnectedCommand):
    name = 'savecalibration'
    help = "Save machine's calibration to yml file"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'filepath': os.path.abspath(self._parsed_args.output_file),
        }
        job = self._jsonrpc.request('savecalibration', params)
        return job

@args(conveyor.arg.positional_output_file)
class LoadCalibrationCommand(_ConnectedCommand):
    name = 'loadcalibration'
    help = "Load machine's calibration to yml file"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'filepath': os.path.abspath(self._parsed_args.output_file),
        }
        job = self._jsonrpc.request('loadcalibration', params)
        return job

class SaveUserCalibrationCommand(_ConnectedCommand):
    name = 'saveusercalibration'
    help = "Saves the current calibration values to the user section of the digitizer's eeprom"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('saveusercalibration', params)
        return job

class SaveFactoryCalibrationCommand(_ConnectedCommand):
    name = 'savefactorycalibration'
    help = "Saves the current calibration values to the factory section of the digitizer's eeprom"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('savefactorycalibration', params)
        return job

class LoadUserCalibrationCommand(_ConnectedCommand):
    name = 'loadusercalibration'
    help = "Loads the current calibration values to the user section of the digitizer's eeprom"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('loadusercalibration', params)
        return job

class LoadFactoryCalibrationCommand(_ConnectedCommand):
    name = 'loadfactorycalibration'
    help = "Loads the current calibration values to the factory section of the digitizer's eeprom"

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
        }
        job = self._jsonrpc.request('loadfactorycalibration', params)
        return job

@args(conveyor.arg.exposure)
@args(conveyor.arg.laser)
@args(conveyor.arg.positional_output_file)
class CaptureImageCommand(_ConnectedCommand):
    name = 'captureimage'
    help = 'capture image'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'exposure': self._parsed_args.exposure,
            'laser': self._parsed_args.laser,
            'output_file': os.path.abspath(self._parsed_args.output_file),

        }
        job = self._jsonrpc.request('captureimage', params)
        return job

@args(conveyor.arg.exposure)
@args(conveyor.arg.laser)
@args(conveyor.arg.positional_output_file)
class CaptureBackgroundCommand(_ConnectedCommand):
    name = 'capturebackground'
    help = 'Calibrate the camera of a digitizer'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'exposure': self._parsed_args.exposure,
            'laser': self._parsed_args.laser,
            'output_file': os.path.abspath(self._parsed_args.output_file),

        }
        job = self._jsonrpc.request('capturebackground', params)
        return job

@args(conveyor.arg.exposure)
@args(conveyor.arg.laser)
@args(conveyor.arg.positional_output_file)
class CaptureBackgroundCommand(_ConnectedCommand):
    name = 'capturebackground'
    help = 'Calibrate the camera of a digitizer'
    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False


    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'exposure': self._parsed_args.exposure,
            'laser': self._parsed_args.laser,
            'output_file': os.path.abspath(self._parsed_args.output_file),

        }
        job = self._jsonrpc.request('capturebackground', params)
        return job

@args(conveyor.arg.toggle_on)
@args(conveyor.arg.toggle_off)
class ToggleCameraCommand(_ConnectedCommand):
    name = 'togglecamera'
    help = 'Toggles camera power on or off'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'toggle': self._parsed_args.toggle,
        }
        job = self._jsonrpc.request('togglecamera', params)
        return job

@args(conveyor.arg.toggle_on)
@args(conveyor.arg.toggle_off)
@args(conveyor.arg.laser)
class ToggleLaserCommand(_ConnectedCommand):
    name = 'togglelaser'
    help = 'Toggles laser power on or off'

    def __init__(self, parsed_args, config):
        _ConnectedCommand.__init__(self, parsed_args, config)
        self._expect_job = False

    def _create_method_job(self):
        params = {
            'machine_name': self._parsed_args.machine_name,
            'toggle': self._parsed_args.toggle,
            'laser': self._parsed_args.laser,
        }
        job = self._jsonrpc.request('togglelaser', params)
        return job

@args(conveyor.arg.mesh_id)
@args(conveyor.arg.positional_input_file)
class LoadMeshCommand(_QueryCommand):
    name = 'loadmesh'
    help = 'Load a mesh to a mesh handle'

    def _create_method_job(self):
        params = {
            'mesh_id': self._parsed_args.mesh_id,
            'input_file': os.path.abspath(self._parsed_args.input_file),
        }
        job = self._jsonrpc.request('mesh_load', params)
        return job

    def _handle_result(self, result):
        print(result)


@args(conveyor.arg.mesh_id)
class CreateMeshCommand(_QueryCommand):
    name = 'createmesh'
    help = 'Create a mesh object and return its handle.'

    def _create_method_job(self):
        params = {
            }
        job = self._jsonrpc.request('mesh_create', params)
        return job

    def _handle_result(self, result):
        print("Mesh Handle: %i" % (result))

@args(conveyor.arg.mesh_id)
class PlaceOnPlatformCommand(_MethodCommand):
    name = 'placeonplatform'
    help = 'Translate a mesh to that its lowest point is touching 0.'

    def _create_method_job(self):
        params = {
            'mesh_id': self._parsed_args.mesh_id,
        }
        job = self._jsonrpc.request('mesh_place_on_platform', params)
        return job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.x_normal)
@args(conveyor.arg.y_normal)
@args(conveyor.arg.z_normal)
@args(conveyor.arg.plane_origin)
@args(conveyor.arg.mesh_id)
class CutPlaneCommand(_MethodCommand):
    name = 'cutplane'
    help = 'Cuts a mesh at a given plane.'

    def _create_method_job(self):
        params = {
            'x_normal': self._parsed_args.x_normal,
            'y_normal': self._parsed_args.y_normal,
            'z_normal': self._parsed_args.z_normal,
            'plane_origin': self._parsed_args.plane_origin,
            'mesh_id': self._parsed_args.mesh_id,
        }
        job = self._jsonrpc.request('mesh_plane_cut', params)
        return job


    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.mesh_id)
@args(conveyor.arg.positional_output_file)
class SaveMeshCommand(_MethodCommand):
    name = 'savemesh'
    help = 'Saves the current mesh'

    def _create_method_job(self):
        params = {
            'mesh_id': self._parsed_args.mesh_id,
            'output_file': os.path.abspath(self._parsed_args.output_file),
        }
        job = self._jsonrpc.request('mesh_save', params)
        return job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.mesh_id)
class DestroyMeshCommand(_MethodCommand):
    name = 'destroymesh'
    help = 'Destroying the current mesh'

    def _create_method_job(self):
        params = {
            'mesh_id': self._parsed_args.mesh_id,
        }
        job = self._jsonrpc.request('mesh_destroy', params)
        return job

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.vid)
@args(conveyor.arg.pid)
@args(conveyor.arg.iserial)
class UsbDeviceInsertedCommand(_MethodCommand):
    name = 'usbdeviceinserted'
    help = 'Send a hotplug event when a usb device is inserted'

    def _create_method_job(self):
        params = {
            'name':    self._parsed_args.name,
            'vid':     self._parsed_args.vid,
            'pid':     self._parsed_args.pid,
            'iserial': self._parsed_args.iserial,
        }
        job = self._jsonrpc.request('usb_device_inserted', params)
        return job 

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.vid)
@args(conveyor.arg.pid)
@args(conveyor.arg.iserial)
class UsbDeviceRemovedCommand(_MethodCommand):
    name = 'usbdeviceremoved'
    help = 'Send a hotplug event when a usb device is removed'

    def _create_method_job(self):
        params = {
            'vid':     self._parsed_args.vid,
            'pid':     self._parsed_args.pid,
            'iserial': self._parsed_args.iserial,
        }
        job = self._jsonrpc.request('usb_device_removed', params)
        return job 

    def _method_callback(self, method_job):
        self._stop_jsonrpc()

@args(conveyor.arg.temperature)
@args(conveyor.arg.tool_index)
class LoadFilamentCommand(_ConnectedCommand):
    name = "loadfilament"
    help = "Orders a machine to load its filament."

    def _create_method_job(self):
        params = {
            "machine_name": self._parsed_args.machine_name,
            'tool_index': self._parsed_args.tool_index,
            'temperature': self._parsed_args.temperature,
        }
        job = self._jsonrpc.request("load_filament", params)
        return job

@args(conveyor.arg.temperature)
@args(conveyor.arg.tool_index)
class UnloadFilamentCommand(_ConnectedCommand):
    name = "unloadfilament"
    help = "Orders a machine to unload its filament."

    def _create_method_job(self):
        params = {
            "machine_name": self._parsed_args.machine_name,
            'tool_index': self._parsed_args.tool_index,
            'temperature': self._parsed_args.temperature,
        }
        job = self._jsonrpc.request("unload_filament", params)
        return job

class GetDigitizerVersionCommand(_ConnectedCommand):
    name = 'getdigitizerversion'
    help = "Gets the digitizer's firmware version"

    def _create_method_job(self):
        self._expect_job = False
        params = {
            'machine_name': self._parsed_args.machine_name}
        job = self._jsonrpc.request('get_digitizer_version', params)
        return job

def _fix_extruder_name(extruder_name):
    if 'right' == extruder_name:
        result = '0'
    elif 'left' == extruder_name:
        result = '1'
    elif 'both' == extruder_name:
        result = '0,1'
    else:
        raise ValueError(extruder_name)
    return result

def _create_slicer_settings(parsed_args, config):
    slicer = conveyor.slicer.Slicer.MIRACLEGRUE
    extruder_name = _fix_extruder_name(parsed_args.extruder_name)
    heat_platform = parsed_args.heat_platform
    slicer_settings_path = parsed_args.slicer_settings_path
    slicer_settings = {
        'path': slicer_settings_path,
        'slicer': slicer,
        'extruder': extruder_name,
        'heat_platform': heat_platform,
        'raft': bool(
            config.get('client', 'slicing', 'raft')),
        'support': bool(
            config.get('client', 'slicing', 'support')),
        'infill': float(
            config.get('client', 'slicing', 'infill')),
        'layer_height': float(
            config.get('client', 'slicing', 'layer_height')),
        'shells': int(
            config.get('client', 'slicing', 'shells')),
        'extruder_temperatures': [float(
            config.get('client', 'slicing', 'extruder_temperature'))]*2,
        'materials': [str(
            config.get('client', 'slicing', 'material'))]*2,
        'platform_temperature': float(
            config.get('client', 'slicing', 'platform_temperature')),
        'print_speed': float(
            config.get('client', 'slicing', 'print_speed')),
        'travel_speed': float(
            config.get('client', 'slicing', 'travel_speed')),
        'default_raft_extruder': str(config.get('client', 'slicing', 'default_raft_extruder')),
        'default_support_extruder': str(config.get('client', 'slicing', 'default_support_extruder')),
        'do_auto_raft': bool(config.get('client', 'slicing', 'do_auto_raft')),
        'do_auto_support': bool(config.get('client', 'slicing', 'do_auto_support')),
    }
    return slicer_settings


def _print_driver_profiles(log, drivers):
    log.info('drivers:')
    for driver in drivers:
        log.info('  %s:', driver['name'])
        for profile in driver['profiles']:
            log.info('    %s:', profile['name'])
            log.info('      X axis size       - %s', profile['xsize'])
            log.info('      Y axis size       - %s', profile['ysize'])
            log.info('      Z axis size       - %s', profile['zsize'])
            log.info('      can print         - %s', profile['can_print'])
            log.info('      heated platform   - %s', profile['has_heated_platform'])
            log.info('      number of tools   - %r', profile['number_of_tools'])
