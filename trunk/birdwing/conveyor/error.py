# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/error.py
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

import os

# NOTE: some exceptions end with `Error` and others with `Exception`. The name
# should have the same ending as the base class. Most of the `Error` classes
# derive from the built-in `KeyError`.


class ConfigKeyError(KeyError):
    '''
    Raised when the configuration is missing a key. Since there are default
    values, the configuration should always be fully populated and this
    exception indicates a programming error.

    '''

    def __init__(self, config_path, key):
        KeyError.__init__(self, key)
        self.config_path = config_path
        self.key = key

    def __str__(self):
        return 'internal error'


class ConfigTypeError(TypeError):
    '''
    Raised when a configuration file element has an invalid type (e.g., it is a
    string instead of a number).

    '''

    def __init__(self, config_path, key, value):
        TypeError.__init__(self, value)
        self.config_path = config_path
        self.key = key
        self.value = value

    def __str__(self):
        return ('invalid type for configuration file element: %s: %s: %s'%
            (e.config_path, e.key, e.value))


class ConfigValueError(ValueError):
    '''
    Raised when a configuration file element has an invalid value (e.g., the
    value for the logging level parameter is not one of the valid logging
    levels).

    '''

    def __init__(self, config_path, key, value):
        ValueError.__init__(self, key, value)
        self.config_path = config_path
        self.key = key
        self.value = value

    def __str__(self):
        return ('invalid value for configuration file element: %s: %s: %s'%
            (e.config_path, e.key, e.value))


class DriverMismatchException(Exception):
    def __str__(self):
        return "the requested driver does not match the machine's current driver"

class NotEnoughExtrudersException(Exception):
    def __str__(self):
        return 'Not enough extruders to print to'


class MachineStateException(Exception):
    def __str__(self):
        return 'the machine is in an invalid state for that operation'


class MissingExecutableException(Exception):
    def __init__(self, path):
        Exception.__init__(self, path)
        self.path = path

    def __str__(self):
        return 'missing executable: %s'% self.path


class LibraryLoadingException(Exception):
    def __init__(self, err):
        Exception.__init__(self, err)
        self.err = err

    def __str__(self):
        return self.err


class MissingFileException(Exception):
    def __init__(self, path):
        Exception.__init__(self, path)
        self.path = path

    def __str__(self):
        return 'missing file: %s'% self.path


class MissingMachineNameException(Exception):
    def __str__(self):
        return 'unable to automatically detect the machine name; please specify a machine name'


class MultipleDriversException(Exception):
    def __str__(self):
        return 'there are multiple drivers available; please specify a driver'


class MultiplePortsException(Exception):
    def __str__(self):
        return 'there are multiple ports available; please specify a port'


class NoDriversException(Exception):
    def __str__(self):
        return 'there are no drivers available'


class NoPortsException(Exception):
    def __str__(self):
        return 'there are no ports available'


class NotFileException(Exception):
    def __init__(self, path):
        Exception.__init__(self, path)

    def __str__(self):
        return 'not a file: %s'% self.path


class PortMismatchException(Exception):
    def __str__(self):
        return "the requested port does not match the machine's current port"


class PrintQueuedException(Exception):
    def __str__(self):
        return 'a print is already queued for the machine'

class ScanQueuedException(Exception):
    def __str__(self):
        return "a scan is already queued for the mahcine"


class NoProfileException(Exception):
    def __str__(self):
        return 'No profiles are available for the given driver'

class ProfileMismatchException(Exception):
    def __str__(self):
        return "the requested profile does not match the machine's current profile"


class UsbNoCategoryException(Exception):
    def __init__(self, vid, pid, iserial):
        Exception.__init__(self, vid, pid, iserial)
        self.vid = vid
        self.pid = pid
        self.iserial = iserial

    def __str__(self):
        return ('unknown category: %04X:%04X:%d'%
            (e.vid, e.pid, e.iserial))


class UnknownDriverError(KeyError):
    def __init__(self, driver_name):
        KeyError.__init__(self, driver_name)
        self.driver_name = driver_name

    def __str__(self):
        return 'unknown driver: %s'% e.driver_name


class UnknownJobError(KeyError):
    def __init__(self, job_id):
        KeyError.__init__(self, job_id)
        self.job_id = job_id

    def __str__(self):
        return 'unknown job: %s'% e.job_id


class UnknownMachineError(KeyError):
    def __init__(self, machine_name):
        KeyError.__init__(self, machine_name)
        self.machine_name = machine_name

    def __str__(self):
        return 'unknown machine: %s'% e.machine_name


class UnknownPortError(KeyError):
    def __init__(self, port_name):
        KeyError.__init__(self, port_name)
        self.port_name = port_name

    def __str__(self):
        return 'unknown port: %s'% e.port_name


class UnknownProfileError(KeyError):
    def __init__(self, profile_name):
        KeyError.__init__(self, profile_name)
        self.profile_name = profile_name

    def __str__(self):
        return 'unknown profile: %s'% e.profile_name


class UnsupportedModelTypeException(Exception):
    def __init__(self, path):
        Exception.__init__(self, path)
        self.path = path

    def __str__(self):
        return 'not a supported model type: %s'% self.path

class UnsupportedJobException(Exception):
    def __str__(self):
        return 'Cannot execute job with input_file as None'

class UnsupportedPlatformException(Exception):
    '''Raised when conveyor does not support your operating system.'''

    def __str__(self):
        return 'conveyor does not support your platform'

class KaitenNotResponsiveException(Exception):
    '''Raised when kaiten does not respond in a timely fashion
    '''
    def __str__(self):
        return 'Kaiten is not responding.'

class MachineAuthenticationError(Exception):
    def __str__(self):
        return "Error authenticating"

class LibDigitizerError(Exception):
    """Raised when libdigitizer does not return a return code of 0"""

    def __str__(self):
        return 'libdigitizer returns a non-0 error code'

class CalibrationNotCompleteError(Exception):

    def __str__(self):
        return "Calibration is not complete"

class CameraNotCalibratedError(Exception):

    def __str__(self):
        return "Camera calibration hasn't been run yet"

class StopScannerJogError(Exception):

    def __init__(self):
        pass

class MachineDisconnectError(Exception):

    def __str__(self):
        return "Machine has disconnected."

class UnknownLaserError(Exception):

    def __str__(self):
        return "Unknown laser"

class NotEnoughCalibrationImagesError(Exception):
    def __str__(self):
        return "Not enough calibration images provided."

class NotEnoughGoodCalibrationImagesError(Exception):
    def __str__(self):
        return "Not enough good calibration images provided."

class CalibrationFailedError(Exception):
    def __str__(self):
        return "Calibration failed."

class DecrementZeroError(Exception):
    def __str__(self):
        return "Cannot decrement counter below 0."

class UnknownMeshIdException(Exception):
    def __str__(self):
        return "Unknown Mesh Id."

class PointsAndNormalsLengthMismatch(Exception):
    def __init__(self, points_length, normals_length):
        self.points_length = points_length
        self.normals_length = normals_length

    def __str__(self):
        log.critical(
            "Points and normals vectors have different lengths: %d, %d",
            self.points_length, self.normals_length, exc_info=True)

class InvalidPointCloudException(Exception):
    def __str__(self):
        return "Trying to act on an uninitialized point cloud"

class CannotWriteOutMultiplePointCloudException(Exception):
    def __str__(self):
        return "Too many point clouds to write out."

class CannotFineAlignException(Exception):
    def __str__(self):
        return "Cannot fine align this point cloud."

class CannotLoadFromIDException(Exception):
    def __str__(self):
        return "Cannot load from id; the given src point cloud is empty."

class UnknownPointCloudIdException(Exception):
    def __str__(self):
        return "Cannot find the point cloud id"

class CannotArchiveException(Exception):
    def __str__(self):
        log.critical("Cannot archive files, no path specified.")

class KaitenPrintException(Exception):
    '''Raised when conveyor fails to sucessfully send and execute a print
        to the kaiten server.
    '''
    def __str__(self):
        return 'Failure printint to kaiten server.'

class IncompatibleFirmwareVersion(Exception):
    """
    Raised when the firmware version got from a machine does not match with
    the expected firmware veriso.
    """
    def __str__(self):
        return "Unexpected firmware version"

class DigitizerNameDecodeError(Exception):
    def __str__(self):
        return "Unable to decode name as UTF-8"

class JobFailedException(Exception):
    ''' Raised when a job is being run synchronously by util.run_job '''
    def __init__(self, failure):
        self.failure = failure

    def __str__(self):
        return 'Unhandled job failure: %r'% self.failure
    
class DigitizerFirmwareAlreadyUploadingException(Exception):
    def __str__(self):
        return "Firmware already beign uploaded"

"""
Below are Digitizer specific errors.  Different error codes returned from
the libdigitizer binary are translated into these execeptions.
"""

class DigitizerException(Exception):
    """Raised when libdigitizer does not return a return code of 0"""

    def __str__(self):
        return 'libdigitizer returns a non-0 error code'

class DigitizerArgumentException(DigitizerException):
    def __str__(self):
        return "Received bad argument"

class DigitizerCameraNotFoundException(DigitizerException):
    def __str__(self):
        return "Failed to find camera"

class DigitizerTimeoutException(DigitizerException):
    def __str__(self):
        return "Digitizer timed out"

class DigitizerPatternNotFoundException(DigitizerException):
    def __str__(self):
        return "Could not find pattern in image"

class DigitizerInsufficientLaserPointsException(DigitizerException):
    def __str__(self):
        return "Could not find enough points to calibrate lasers"

def guard(log, func):
    try:
        code = func()
    except KeyboardInterrupt:
        code = 0
        log.warning('interrupted')
        log.debug('handled exception', exc_info=True)
    except SystemExit as e:
        code = e.code
        log.debug('handled exception', exc_info=True)
    except Exception as e:
        code = 1
        log.critical(e, exc_info=True)
    except:
        code = 1
        log.critical('internal error', exc_info=True)
    return code
