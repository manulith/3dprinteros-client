# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4 :
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

"""
Digitizer code for conveyor.

This file is a mess.  Its super complicated (IMO unnecessarily so), and is way
too big.  We should reduce the amount of repeated code and architect something
that is easier to deal with.
"""

from __future__ import (absolute_import, print_function, unicode_literals)

import collections
import ctypes
import datetime
import json
import os
import sys
import time
import tempfile
import threading
import time
import warnings

import usb.core
import usb.util

import conveyor.enum
import conveyor.machine
import conveyor.job
import conveyor.util

#import conveyor.machine.digitizer_windows

_firmware_store = None
def global_get_firmware_store():
    """
    Gets the global firmware store.  The firwmare store keeps track of machines
    that we are going to upload firmware to with their firmware paths.

    At its core is a dict in the form of: {iserial: hex_path}. When a user
    requests to upload firmware to a digitizer board, that board will make
    a new entry in the firmware_store with the user specified hex file
    keyed by its iserial number.  When the bootloader starts up, it queries
    the firmware_store, checking to see if it has an entry for its iserial
    number.  If it does, it assumes it needs to upload firmware.
    """
    global _firmware_store
    if None is _firmware_store:
        class FirmwareStore(collections.defaultdict):
            """
            Store object.  Inherits from defaultdict so we can leverage the
            convenienve of indexing while adding potential convenience
            functions and objects.
            """
            condition = threading.Condition()
        _firmware_store = FirmwareStore()
    return _firmware_store

class DigitizerDriver(conveyor.machine.Driver):

    @staticmethod
    def create(config, profile_dir):
        driver = DigitizerDriver(config)
        for profile_name in os.listdir(profile_dir):
            with open(os.path.join(profile_dir, profile_name)) as f:
                digit_prof = json.load(f)
            profile = _DigitizerProfile.create(digit_prof['type'], driver,
                digit_prof)
            driver._profiles[profile.name] = profile
        return driver

    def __init__(self, config):
        conveyor.machine.Driver.__init__(self, 'digitizer', config)
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
        """
        Precondition: port.machine is None
        Creates a new machine

        @param port: Port object
        @param profile: Profile object
        """
        # Check that the profile is concrete and not the profile name
        if None is profile:
            raise conveyor.error.UnknownProfileError(None)
        elif not isinstance(profile, _DigitizerProfile):
            profile = self.get_profile(profile)
        # Check that the profile is correct
        machine = self._create_machine(port, self, profile)
        return machine

    def _create_machine(self, machine_name, driver, profile):
        return DigitizerMachine(machine_name, self, profile)

class ComponentContext(object):
    def __init__(self, entercallback, exitcallback, name):
        self._log = conveyor.log.getlogger(self)
        self._count = 0
        self._enter = entercallback
        self._exit = exitcallback
        self._name = name

    def __enter__(self):
        self._log.debug("Checking Enter for %s", self._name)
        if self._should_create():
            self._log.debug("Calling Enter callback for %s", self._name)
            self._enter()
        self.increment()

    def __exit__(self, *args, **kwargs):
        self._log.debug("Checking Exit for %s", self._name)
        if self._should_destroy():
            self._log.debug("Calling Exit callback for %s", self._name)
            self._exit()
        self.decrement()

    def increment(self):
        self._count += 1

    def decrement(self):
        if self._count == 0:
            raise conveyor.error.DecrementZeroError
        self._count -= 1

    def _should_create(self):
        return self._count == 0

    def _should_destroy(self):
        return self._count == 1

class PointCloud(object):
    def __init__(self):
        self.points = None
        self.normals = None

    def is_initialized(self):
        return None is not self.points and None is not self.normals

    def reset(self):
        self.points = None
        self.normals = None

class PointCloudData(object):
    def __init__(self):
        self.left_cloud = PointCloud()
        self.right_cloud = PointCloud()
        self.condition = threading.Condition()

    def get_cloud(self, cloud):
        return getattr(self, "%s_cloud" % (cloud))

    def iter_clouds(self):
        return filter(lambda cloud: cloud.is_initialized(), [self.left_cloud,
            self.right_cloud])

    def can_fine_align(self):
        return (None is not self.left_cloud and
                self.left_cloud.is_initialized() and
                None is not self.right_cloud and
                self.right_cloud.is_initialized())

    def get_cloud_to_save(self):
        clouds = filter(lambda cloud: cloud.is_initialized(),
            self.iter_clouds())
        if len(clouds) > 1:
            raise conveyor.error.CannotWriteOutMultiplePointCloudException
        else:
            return clouds[0]

class PointCloudContainer(object):
    def __init__(self, config):
        self._log = conveyor.log.getlogger(self)
        self._config = config
        self._interface = _DigitizerLibraryInterface(self._config)
        self.point_clouds = {}
        self._point_cloud_id = 0
        self._point_cloud_condition = threading.Condition()

    def check_point_cloud_id(func):
        def decorator(*args, **kwargs):
            try:
                value = func(*args, **kwargs)
            except KeyError:
                raise conveyor.error.UnknownPointCloudIdException
            else:
                return value
        return decorator

    def point_cloud_create(self):
        with self._point_cloud_condition:
            new_id = self._point_cloud_id
            self.point_clouds[new_id] = PointCloudData()
            self._point_cloud_id += 1
        return new_id

    def point_cloud_load(self, point_cloud_id, side, input_file):
        self._log.debug("Loading %s to the %s side", input_file, side)
        cloud = self.get_point_cloud(point_cloud_id)
        the_cloud = getattr(cloud, '%s_cloud' % (side))
        the_cloud.points = self._interface.create_vector()
        the_cloud.normals = self._interface.create_vector()
        self._interface.points_load(the_cloud.points,
            the_cloud.normals, input_file)

    def point_cloud_load_from_id(self, src_id, src_side, dst_id, dst_side):
        """
        Copies point cloud from one PointCloudData object to another
        """
        src_cloud_data = self.get_point_cloud(src_id)
        dst_cloud_data = self.get_point_cloud(dst_id)
        # srd_side and dst_side are ints in the jsonrpc API
        with src_cloud_data.condition, dst_cloud_data.condition:
            src_cloud = getattr(src_cloud_data, '%s_cloud' % (src_side))
            dst_cloud = getattr(dst_cloud_data, '%s_cloud' % (dst_side))

            if not (None is not src_cloud and src_cloud.is_initialized()):
                raise conveyor.error.CannotLoadFromIDException

            if not None is dst_cloud and dst_cloud.is_initialized():
                self._interface.vector_destroy(dst_cloud.points)
                self._interface.vector_destroy(dst_cloud.normals)

            dst_cloud.points = self._interface.create_vector()
            dst_cloud.normals = self._interface.create_vector()
            self._interface.vector_append(dst_cloud.points, src_cloud.points)
            self._interface.vector_append(dst_cloud.normals, src_cloud.normals)

    @check_point_cloud_id
    def get_point_cloud(self, point_cloud_id):
        return self.point_clouds[point_cloud_id]

    def point_cloud_destroy(self, point_cloud_id):
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            for cloud in cloud_data.iter_clouds():
                self._destroy_point_cloud(cloud)
            self.point_clouds.pop(point_cloud_id)

    def _destroy_point_cloud(self, point_cloud):
        self._interface.destroy_vectors(point_cloud.points,
            point_cloud.normals)
        point_cloud.reset()

    def point_cloud_save(self, point_cloud_id, output_path):
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            cloud = cloud_data.get_cloud_to_save()
            self._interface.points_save(cloud.points, cloud.normals,
                output_path)

    def point_cloud_process(self, point_cloud_id, grid_size, nearest_neighbors,
            adaptive_sigma, smoothing_nearest_neighbors, smoothing_iterations,
            fixed_cutoff_percent, remove_outliers):
        """
        Takes the final pointcloud and executes all necessary processes on
        it. Then save it.

        NB: We assume here that when we do a dual laser scan, the
        pointclouds are merged into the left pointcloud.
        """
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            for cloud in cloud_data.iter_clouds():
                self._interface.downsample(cloud.points, cloud.normals,
                    grid_size)
                if remove_outliers:
                    self._interface.remove_outliers_adaptive(cloud.points,
                        cloud.normals, nearest_neighbors, adaptive_sigma)
                    self._interface.remove_outliers_fixed(cloud.points,
                        cloud.normals, nearest_neighbors, fixed_cutoff_percent)
                self._interface.estimate_normals(cloud.points,
                    cloud.normals, nearest_neighbors)
                self._interface.points_smooth(cloud.points, cloud.normals,
                    smoothing_nearest_neighbors, smoothing_iterations, True,
                    True)

    def point_cloud_fine_alignment(self, point_cloud_id, sample_rate,
            max_samples, inlier_ratio, max_iterations):
        """
        Finely Aligns the two point clouds

        @param int point_handle: Handle to the pointcloud object
        @param float sample_rate: How many points to cull before executing file alighment
        @param int max_samples: If samplerate is too high, max samples is used.
        @param float inlier ratio: Number of points to remove during fine alignment.  <Number of points to throw away>/<Number of points to keep>.
        @param int max_iterations: Number of times we iteratively move the scene to the model.  If we are too close for another iteration, "digitizer_vector_fine_align will return.
        """
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            if not cloud_data.can_fine_align():
                raise conveyor.error.CannotFineAlignException
            transform_matrix = ctypes.c_void_p()
            self._interface.matrix_create(transform_matrix)
            pre_error = ctypes.c_float()
            post_error = ctypes.c_float()
            self._interface.fine_align(cloud_data.left_cloud.points,
                cloud_data.right_cloud.points, transform_matrix,
                pre_error, post_error, sample_rate, max_samples,
                inlier_ratio, max_iterations)
            self._interface.matrix_invert(transform_matrix)
            self._interface.points_transform(cloud_data.right_cloud.points,
                cloud_data.right_cloud.normals, transform_matrix)
            self._interface.points_merge(cloud_data.left_cloud.points,
                cloud_data.left_cloud.normals, cloud_data.right_cloud.points,
                cloud_data.right_cloud.normals, 2)
            self._destroy_point_cloud(cloud_data.right_cloud)
            self._interface.matrix_destroy(transform_matrix)

    def point_cloud_coarse_alignment(self, point_cloud_id):
        """
        Coarsely aligns right point cloud to left point cloud
        """
        nearest_neighbors = 20
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            try:
                self._interface.estimate_normals(cloud_data.left_cloud.points,
                    cloud_data.left_cloud.normals, nearest_neighbors)
                self._interface.estimate_normals(cloud_data.right_cloud.points,
                    cloud_data.right_cloud.normals, nearest_neighbors)
                transform_matrix = ctypes.c_void_p()
                self._interface.matrix_create(transform_matrix)
                self._interface.coarse_align(cloud_data.left_cloud.points,
                    cloud_data.left_cloud.normals, cloud_data.right_cloud.points,
                    cloud_data.right_cloud.normals, transform_matrix)
                self._interface.matrix_invert(transform_matrix)
                self._interface.points_transform(cloud_data.right_cloud.points,
                    cloud_data.right_cloud.normals, transform_matrix)
            except Exception as e:
                self._log.info("Failed to coarse align point clouds")
                raise e
            finally:
                self._interface.matrix_destroy(transform_matrix)

    def point_cloud_global_alignment(self, point_cloud_id, input_files,
            sample_rate, max_samples, inlier_ratio, max_iterations):
        """
        Loads first point cloud in given list into left point cloud of
        the given point_cloud_id; All others are loaded into the right cloud,
        then coarsely and finely aligned and merged into the left point cloud
        """

        # total is kept in a left point cloud and model is kept in a right cloud.
        # (there is no particular functional reason for this-- just that in
        # normal scanning, the point clouds are merged into the left)
        point_cloud_data = self.get_point_cloud(point_cloud_id)
        self.point_cloud_load(point_cloud_id, 'left', input_files[0])

        for i in range(1, len(input_files)):
            self.point_cloud_load(point_cloud_id, 'right', input_files[i])
            try:
                self.point_cloud_coarse_alignment(point_cloud_id)
            except conveyor.error.DigitizerException:
                self._log.info("Failed to global align %s", input_files[i])
            finally:
                self.point_cloud_fine_alignment(point_cloud_id, sample_rate,
                    max_samples, inlier_ratio, max_iterations)
                self._destroy_point_cloud(point_cloud_data.right_cloud)

    def point_cloud_crop(self, point_cloud_id, side, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius):
        """
        Remove points outside of cylinder
        """
        cloud_data = self.get_point_cloud(point_cloud_id)
        with cloud_data.condition:
            the_cloud = getattr(cloud_data, '%s_cloud' % (side))
            if None is not the_cloud and the_cloud.is_initialized():
                self._interface.remove_outside_cylinder(the_cloud.points,
                    the_cloud.normals, bounding_cylinder_top,
                    bounding_cylinder_bottom, bounding_cylinder_radius)
            else:
                raise conveyor.error.InvalidPointCloudException


# TODO(nicholasbishop): would use UsbPort for this, but it requires a
# category which would make it a candidate for machine scanning... for
# now less risky to just use a local type
UsbInfo = collections.namedtuple('UsbInfo', ['vid', 'pid', 'serial'])

def is_camera(vid, pid):
    return vid == 0x23c1 and pid == 0x0001

def find_camera_from_board(board_serial):
    """Get the VID, PID, and serial of a Digitizer board's camera

    We match up the Digitizer board with the correct camera by packing
    the vid, pid, and serial of the camera into the board's serial.

    Searches all USB devices for a match with expected_camera. Returns
    the camera VID, PID, and serial if a match is found, otherwise
    returns None.

    """
    expected_camera = UsbInfo(
        vid = int(board_serial[0:4], 16),
        pid = int(board_serial[4:8], 16),
        serial = board_serial[8:16])

    if (sys.platform != 'win32'):
        # pyusb consistently works on anything but Windows.
        # Find all cameras with the expected VID/PID
        camera_devices = usb.core.find(
            idVendor = expected_camera.vid,
            idProduct = expected_camera.pid,
            find_all = True)

        # Look for the camera with the expected serial. This match must be
        # case insensitive. (Is that really true? I'm basing this comment
        # off what the existing code did, but not sure if we are actually
        # inconsistent with the serial-string's case in production.)
        for dev in camera_devices:
            serial = usb.util.get_string(dev, dev.iSerialNumber)
            if serial.lower() == expected_camera.serial.lower():
                return UsbInfo(
                    vid = dev.idVendor,
                    pid = dev.idProduct,
                    serial = serial)
    else:
        # No good answer for this right now.  Take the expected serial number
        # and hope for the best.
        return expected_camera
                    
    # Camera not found
    return None

class DigitizerMachine(conveyor.stoppable.StoppableInterface, conveyor.machine.Machine):

    def __init__(self, port, driver, profile):
        conveyor.stoppable.StoppableInterface.__init__(self)
        conveyor.machine.Machine.__init__(self, port, driver, profile)
        self._stop = False
        self._camera_intrinsics = None
        self._turntable_extrinsics = None
        self._left_laser_extrinsics = None
        self._right_laser_extrinsics = None
        self._camera_calibrated = False
        self._laser_map = {
            'left': 0,
            'right': 1,
        }
        self._interface = _DigitizerLibraryInterface(self._driver._config)

        # This event is triggered whenever the camera device is closed
        self.camera_closed_event = conveyor.event.Event('camera_closed')

        self._camera_device_path = None

        # After opening the camera, an artificial delay must be
        # inserted before capturing images with a particular exposure.
        #
        # Some operations, such as getting the camera device string,
        # are OK to do without the delay, so the delay is only
        # inserted when it has to be (and only one time until the next
        # time the camera is opened).
        self._camera_open_delay_completed = False

        # Careful! Tricky design here, the camera/board contexts take
        # the lock only during enter and exit, not for the full period
        # the context is in use by a 'with' block.
        #
        # This means that in general you have to use both with a
        # 'with' block. TODO: we should revisit this and check if the
        # distinction is needed, it's pretty confusing.

        self._camera_condition = threading.Condition()
        self._camera_context = ComponentContext(self._initialize_camera,
            self._destroy_camera, 'camera')
        self._board_condition = threading.Condition()
        self._board_context = ComponentContext(self._initialize_board,
            self._destroy_board, 'board')
        self._state_context = ComponentContext(self._goto_running,
            self._goto_idle, 'digitizer_state_machine')
        self._reprojection_errors = None
        self._mesh = None
        #delay time in microseconds
        self._delay_time = 190000
        self._calib_fail_count_to_skip = 10
        self._calib_resolution = {
            'turntable': 800,
            'camera': 36
        }
        self._calib_error_threshold = {
            'turntable': 0.05,
            'camera': 0.5,
            'laser': 0.1
        }
        self._calib_min_good_images = {
            'turntable': 200,
            'camera': 5
        }
        # Sector refer to a fraction of the total images taken that are
        # searched at a time for the checkerboard pattern during calibration.
        self._calib_num_sectors = {
            'turntable': 4,
            'camera': 3
        }
        self._job = None

    def _goto_running(self):
        """
        Transitions into the busy state.  Used in the state_context
        """
        with self._state_condition:
            self._state = conveyor.machine.MachineState.RUNNING

    def _goto_idle(self):
        """
        Transitions into the idle state ONLY if we are currently in the busy
        state.  Used in the state_context.
        """
        with self._state_condition:
            self._state = conveyor.machine.MachineState.IDLE

    def _machine_state_change(func):
        """
        Decorator function executes a function with the self._state_context
        object, which handles the state transition.  Decorator function to
        ensure we do the correct machine state changes around each function.

        Since we use the reference counting _state_context, we can have
        subfunctions be decorated with this and not fear the switch back to the
        idle state.

        Because we assume the first arg is self, this decorator CANNOT be
        used on @staticmethod functions.
        """
        def decorator(*args, **kwargs):
            # We assume the first arg is self, for better or for worse
            self = args[0]
            with self._state_context:
                return_value = func(*args, **kwargs)
            return return_value
        return decorator

    def _initialize_board(self):
        self._log.info("Creating digitizer board for %s", self.name)
        with self._board_condition:
            port_path = self.get_port().get_serial_port_name()
            self._board = ctypes.c_void_p()
            self._interface.board_create(port_path, self._board)
            self._board_condition.notify_all()

    def _destroy_board(self):
        """
        Unlike _destroy_camera, there haven't been any wacky situations
        that require us to do any implicit checking before we destroy
        the board.
        """
        self._log.info("Destroying board %s", self.name)
        with self._board_condition:
            self._interface.board_destroy(self._board)
            self._board = None
            self._board_condition.notify_all()

    def _turntable_jog(self, resolution, steps):
        with self._board_condition:
            self._interface.jog(self._board, resolution, steps)
            self._board_condition.notify_all()

    def _initialize_camera(self):
        board_serial = self.get_port().get_iserial()
        camera_info = find_camera_from_board(board_serial)
        if not camera_info:
            raise Exception('Camera matching board serial {} not found'.format(
        	board_serial))

        self._log.info(
            "Creating digitizer camera for %s, vid=%s, pid=%s, serial=%s",
            self.name, camera_info.vid, camera_info.pid, camera_info.serial)
        with self._camera_condition:
            # Capture resolution during scan
            width = 1280
            height = 1024

            self._camera = ctypes.c_void_p()
            self._interface.camera_create(
                camera_info, width, height, self._camera)

            # Get camera device path so that clients can open the camera
            path = self._interface.digitizer_camera_device_path(self._camera)
            self._camera_device_path = path

            self._camera_open_delay_completed = False
            self._camera_condition.notify_all()

    def _camera_insert_delay(self):
        """Insert an artificial pause to ensure exposure settings work"""
        with self._camera_condition:
            if not self._camera_open_delay_completed:
                # This warm-up delay is needed after opening the
                # camera device to ensure that the exposure level is
                # correct.
                self._log.debug('Inserting artificial delay before camera use')
                time.sleep(2)
                self._camera_open_delay_completed = True

    def _camera_set_exposure_with_reinit(self, exposure, autoexposure=False):
        """This function exists due to a bug with the digitizers camera
        that causes the exposure not to be set correctly until the camera
        is re-initialized.
        """
        with self._camera_condition:
            self._interface.set_camera_exposure(self._camera, exposure,
                autoexposure)
            self._interface.camera_destroy(self._camera)
            self._camera = None
            self._initialize_camera()
            self._interface.set_camera_exposure(self._camera, exposure,
                autoexposure)

    def _destroy_camera(self):
        """
        Destroys the camera.
        The scan job requires us to destroy the camera in the
        cancel callback.  This introdues a state where we could
        potentially try to destroy a camera that has already been
        destroyed.  So we always check to make sure the camera
        isn't none before we destroy it.
        """
        self._log.info("Destroying camera for %s", self.name)
        with self._camera_condition:
            if None is not self._camera:
                self._interface.set_camera_exposure(self._camera, 1,
                    autoexposure=True)
                self._interface.camera_destroy(self._camera)
                self._camera = None
                self.camera_closed_event(self)
                self._camera_condition.notify_all()

    def _camera_grab(self, camera, img):
        with self._camera_condition:
            self._interface.camera_grab(camera, img)
            self._camera_condition.notify_all()

    def _connect_to_board(self):
        with self._board_context, self._board_condition:
            with self._camera_context:
                # Just tests that camera is OK (throws an exception if
                # otherwise)
                pass
            self._board_condition.notify_all()
        with self._state_condition:
            self._state = conveyor.machine.MachineState.IDLE

    def upload_firmware(self, hex_file, job):
        if not os.path.exists(hex_file):
            raise IOError(hex_file)
        def running_callback(job):
            self._upload_firmware_implementation(hex_file, job)
        job.runningevent.attach(running_callback)

    @_machine_state_change
    def _upload_firmware_implementation(self, hex_file, job):
        """
        Begins the firmware uploading process by registering this machine's
        iserial number hex file with the global firmware store.  If this
        iserial number already exists, we fail since we probably already
        told this machine to upload firmware.

        As soon as this function is done, this machine is going to disconnect.
        """
        iserial = self.get_port().get_iserial()
        store = global_get_firmware_store()
        with store.condition:
            if iserial in store:
                self._log.info("%s has already been told to upload firmare, failing.", self.name)
                raise conveyor.error.DigitizerFirmwareAlreadyUploadingException
            else:
                success = False
                store[iserial] = [hex_file, job, success]
        with self._board_context, self._board_condition:
            self._interface.digitizer_reset_into_bootloader(self._board)

    @_machine_state_change
    def connect(self):
        # Create connection to board
        self._connect_to_board()
        self._log.info("Connected to digitizer machine with version: %r",
            self.get_firmware_version())

    @_machine_state_change
    def _get_firmware_version_implementation(self):
        """
        Asks libdigitizer to ask the board what its firmware version is
        """
        with self._board_context, self._board_condition:
            major = ctypes.c_int()
            minor = ctypes.c_int()
            revision = ctypes.c_int()
            try:
                self._interface.digitizer_get_firmware_version(self._board,
                    major, minor, revision)
                return (major.value, minor.value, revision.value)
            except Exception as e:
                self._log.info("Digitizer has no firmware version (probably because it is so old)")

    def get_firmware_version(self):
        return self._get_firmware_version_implementation()

    @_machine_state_change
    def disconnect(self):
        """
        AFAICT This function is only called when conveyor is shutting down.
        If the machine is unplugged, this function is not called.
        This is actually annoying, since we need to then constantly be creating
        and destroying things like the 'board' object, since they rely on the
        port location.
        """
        self._interface.camera_intrinsics_destroy(self._camera_intrinsics)
        self._interface.turntable_extrinsics_destroy(self._turntable_extrinsics)
        for lext in [self._left_laser_extrinsics, self._right_laser_extrinsics]:
            self._interface.laser_extrinsics_destroy(lext)
        with self._state_condition:
            self._state = conveyor.machine.MachineState.DISCONNECTED

    def stop(self):
        self._stop = True
        self.disconnect()
        with self._state_condition:
            self._state_condition.notify_all()

    @_machine_state_change
    def get_info(self):
        return super(DigitizerMachine, self).get_info()

    def is_idle(self):
        return self._state == conveyor.machine.MachineState.IDLE

    @_machine_state_change
    def toggle_camera(self, toggle):
        with self._board_condition:
            self._interface.toggle_camera(self._board, toggle)
            self._board_condition.notify_all()

    @_machine_state_change
    def toggle_laser(self, toggle, laser):
        lasers = self._parse_lasers(laser)
        self._log.debug("Toggling lasers %r" % (lasers))
        with self._board_context, self._board_condition:
            for l in lasers:
                self._interface.toggle_laser(self._board,
                    self._laser_map[l], toggle)
            self._board_condition.notify_all()

    def _create_calibration_objects(self):
        self._camera_intrinsics = ctypes.c_void_p()
        self._turntable_extrinsics = ctypes.c_void_p()
        self._left_laser_extrinsics = ctypes.c_void_p()
        self._right_laser_extrinsics = ctypes.c_void_p()
        self._interface.camera_intrinsics_create(self._camera_intrinsics)
        self._interface.turntable_extrinsics_create(
            self._turntable_extrinsics)
        for lext in [self._left_laser_extrinsics, self._right_laser_extrinsics]:
            self._interface.laser_extrinsics_create(lext)

    @_machine_state_change
    def load_factory_calibration(self):
        self._create_calibration_objects()
        with self._board_context, self._board_condition:
            self._interface.load_calibration_from_factory_eeprom(self._board,
                self._camera_intrinsics, self._turntable_extrinsics,
                self._left_laser_extrinsics, self._right_laser_extrinsics)

    @_machine_state_change
    def load_user_calibration(self):
        self._create_calibration_objects()
        with self._board_context, self._board_condition:
            self._interface.load_calibration_from_user_eeprom(self._board,
                self._camera_intrinsics, self._turntable_extrinsics,
                self._left_laser_extrinsics, self._right_laser_extrinsics)
            self._camera_calibrated = True

    @_machine_state_change
    def save_factory_calibration(self):
        if not self._is_calibrated():
            raise conveyor.error.CalibrationNotCompleteError
        else:
            with self._board_context, self._board_condition:
                self._interface.save_calibration_to_factory_eeprom(self._board,
                    self._camera_intrinsics, self._turntable_extrinsics,
                    self._left_laser_extrinsics, self._right_laser_extrinsics)

    @_machine_state_change
    def save_user_calibration(self):
        if not self._is_calibrated():
            raise conveyor.error.CalibrationNotCompleteError
        else:
            with self._board_context, self._board_condition:
                self._log.debug('writing user calibration to EEPROM')
                self._interface.save_calibration_to_user_eeprom(self._board,
                    self._camera_intrinsics, self._turntable_extrinsics,
                    self._left_laser_extrinsics, self._right_laser_extrinsics)
                self._log.debug('finished writing user calibration to EEPROM')

    @_machine_state_change
    def digitizer_invalidate_user_calibration(self):
        with self._board_context, self._board_condition:
            self._interface.digitizer_invalidate_user_calibration(self._board)

    @_machine_state_change
    def load_calibration(self, calib_path):
        self._create_calibration_objects()
        self._interface.calibration_load(calib_path,
            self._camera_intrinsics, self._turntable_extrinsics,
            self._left_laser_extrinsics, self._right_laser_extrinsics)
        self._camera_calibrated = True

    #DEPRECATED. USE calibrate_camera INSTEAD
    @_machine_state_change
    def calibrate_camera_deprecated(self, images):
        """
        Camera calibration needs to occur first, since all calibration steps
        rely on the "camera_intrinsics" file.  We require at least 7
        images for calibration: 5 for the main calibration and 2 for
        the calibration validation.
        """
        self._log.error("WARNING: Using deprecated method of camera calibration")
        min_images = 7
        if len(images) < min_images:
            raise conveyor.error.NotEnoughCalibrationImagesError
        calibration_images = images #[:-2]
        #validation_images = images[-2:]
        self._log.info("Calibrating camera for %s", self.name)

        self._camera_intrinsics = ctypes.c_void_p()
        self._interface.camera_intrinsics_create(self._camera_intrinsics)
        calib = ctypes.c_void_p()
        self._interface.camera_calibration_create(calib)

        image = self._interface.create_image()
        failed_images = []
        for img in calibration_images:
            self._interface.image_load(image, img)
            try:
                self._interface.camera_add_image(calib, image)
            except conveyor.error.DigitizerPatternNotFoundException:
                failed_images.append(calibration_images.index(img))
        if len(images) - len(failed_images) < min_images:
            #return calibration error value of -1 if not enough images
            self._log.info("Took %i images (%i succeeded)" % (len(images),
                len(images) - len(failed_images)))
            return -1, failed_images
        camera_error = ctypes.c_float()
        self._interface.camera_calibrate(calib, self._camera_intrinsics,
            camera_error)
        self._interface.camera_calibration_destroy(calib)
        self._interface.matrix_destroy(image)

        #User won't be taking validation images, but keeping this here
        #for future debugging purposes.
        """
        total_error = 0.0
        for val_img in validation_images:
            img = self._interface.create_image()
            self._interface.image_load(img, val_img)
            error = ctypes.c_float()
            self._interface.camera_calibration_verify(calib,
                self._camera_intrinsics, img, error)
            total_error += error.value
        error_threshold = 1
        self._interface.camera_calibration_destroy(calib)
        self._interface.matrix_destroy(image)
        if total_error > error_threshold:
            raise conveyor.error.CameraCalibrationFailedError
        else:
            self._reprojection_error = total_error
            self._camera_calibrated = True
        """
        self._log.info("Took %i images (%i succeeded)" % (len(images),
            len(images) - len(failed_images)))
        self._log.info("Camera calibration error value: %.5f", camera_error.value)
        return camera_error.value, failed_images

    def get_reprojection_error(self):
        if not self._camera_calibrated:
            raise conveyor.error.CameraNotCalibratedError
        return self._reprojection_error

    #DEPRECATED. USE calibrate_turntable INSTEAD
    @_machine_state_change
    def calibrate_turntable_deprecated(self):
        self._log.error("WARNING: Using deprecated method of turntable calibration")
        self._log.info("Calibrating turntable for %s", self.name)
        if not self._camera_calibrated:
            raise conveyor.error.CameraNotCalibratedError

        calib = ctypes.c_void_p()
        self._interface.turntable_calibration_create(calib)
        self._turntable_extrinsics = ctypes.c_void_p()
        self._interface.turntable_extrinsics_create(self._turntable_extrinsics)
        self._interface.turntable_calibration_set_params(
            calib, self._camera_intrinsics)
        with self._camera_context, self._board_context, self._board_condition, self._camera_condition:
            self._interface.motor_lock(self._board, True)
            image = self._interface.create_image()
            succeeded_count = self._calib_resolution['turntable']
            for i in range(self._calib_resolution['turntable']):
                self._camera_grab(self._camera, image)
                try:
                    self._interface.turntable_add_image(calib, image)
                except conveyor.error.DigitizerPatternNotFoundException:
                    self._log.info("Could not find pattern in image %i", i)
                    succeeded_count -= 1
                self._turntable_jog(self._calib_resolution['turntable'],1)
            self._interface.motor_lock(self._board, False)
        turntable_error = ctypes.c_float()
        self._interface.turntable_calibrate(calib, self._turntable_extrinsics,
            turntable_error)
        self._interface.turntable_calibration_destroy(calib)
        self._interface.matrix_destroy(image)

        self._log.info("Took %i images (%i succeeded)" %
            (self._turntable_calib_resolution, succeeded_count))
        self._log.info("Turntable calibration error value: %.5f",
            turntable_error.value)
        return turntable_error.value

    @_machine_state_change
    def calibrate_laser(self, calibration_images, laser_images, laser):
        """
        Takes a list of calibration images and laser images. Calibration_images
        and laser_images are added in lockstep, so they are expected to be
        associated by their indecies.
        """
        self._log.info("Calibrating %s laser for %s", laser, self.name)
        if not self._camera_calibrated:
            raise conveyor.error.CameraNotCalibratedError
        if laser not in ["left", "right"]:
            raise conveyor.error.UnknownLaserError
        calib = ctypes.c_void_p()
        self._interface.laser_calibration_create(calib)
        laser_extrinsics = ctypes.c_void_p()
        self._interface.laser_extrinsics_create(laser_extrinsics)
        threshold = 200
        inlier_percent = 0.6
        inlier_threshold = 0.25
        self._interface.laser_calibration_set_params(calib,
            self._camera_intrinsics, threshold, inlier_percent,
            inlier_threshold)
        calib_image_pointer = self._interface.create_image()
        laser_image_pointer = self._interface.create_image()
        try:
            for calib_img, laser_img in zip(calibration_images, laser_images):
                self._interface.image_load(calib_image_pointer,
                    calib_img)
                self._interface.image_load(laser_image_pointer,
                    laser_img)
                self._interface.laser_add_image(calib, calib_image_pointer,
                    laser_image_pointer)

            laser_error = ctypes.c_float()
            self._interface.laser_calibrate(calib, laser_extrinsics, laser_error)
            self._log.info("%s laser calibration error value: %.5f", laser,
                laser_error.value)
            if laser_error.value > self._calib_error_threshold['laser']:
                raise conveyor.error.CalibrationFailedError
            # Only if the above code gets executed do we want to assign the
            # calibration object, otherwise we keep our old one
            self._interface.laser_extrinsics_destroy(
                getattr(self, "_%s_laser_extrinsics" % (laser)))
            setattr(self, "_%s_laser_extrinsics" % (laser), laser_extrinsics)
        except Exception as e:
            raise e
        finally:
            # We always want to clean up our C objects
            self._interface.camera_calibration_destroy(calib)
            for pointer in [calib_image_pointer, laser_image_pointer]:
                self._interface.matrix_destroy(pointer)

    @_machine_state_change
    def save_calibration(self, filepath):
        """
        Assumes all calibration steps have been completed.
        """
        self._log.info("Saving calibration to %s for %s", filepath, self.name)
        if not self._is_calibrated():
            raise conveyor.error.CalibrationNotCompleteError
        self._interface.calibration_save(filepath, self._camera_intrinsics,
            self._turntable_extrinsics, self._left_laser_extrinsics,
            self._right_laser_extrinsics)

    @_machine_state_change
    def capture_image(self, exposure, laser, output_file):
        with self._camera_context, self._board_context, self._camera_condition:
            self._camera_insert_delay()
            self._camera_set_exposure_with_reinit(exposure)
            image = self._interface.create_image()
            self.toggle_laser(True, laser)
            self._camera_grab(self._camera, image)
            self.toggle_laser(False, laser)
            self._interface.image_save(image, output_file)
            self._interface.matrix_destroy(image)

    @_machine_state_change
    def capture_image_auto_exposure(self, output_file):
        """Precondition: the camera must already be in auto-exposure mode"""
        with self._camera_context, self._camera_condition:
            self._camera_insert_delay()
            image = self._interface.create_image()
            self._camera_grab(self._camera, image)
            self._interface.image_save(image, output_file)
            self._interface.matrix_destroy(image)

    """
    Old capture_background. keeping around just in case...
    @_machine_state_change
    def capture_background(self, laser, output_file):

        self._log.info("Capturing background for %s", self.name)
        with self._camera_context:
            self._camera_insert_delay()
            bg_image = self._interface.create_image()
            self.toggle_laser(True, laser)
            num_frames = 10
            self._interface.capture_background(self._camera, bg_image, num_frames)
            self.toggle_laser(False, laser)
            self._interface.image_save(bg_image, output_file)
            self._interface.matrix_destroy(bg_image)
    """

    @_machine_state_change
    def capture_background(self, laser, bg_image):
        """Uses auto-exposure for aggressive background subtraction."""
        self._log.info("Capturing background for %s", self.name)
        with self._camera_context, self._camera_condition:
            self._camera_insert_delay()
            # bg_image = self._interface.create_image()
            self.toggle_laser(True, laser)
            num_frames = 10
            self._interface.capture_background(self._camera, bg_image, num_frames)
            self.toggle_laser(False, laser)

    """
    Load Digitizer name from EEPROM encoded in "UTF-8" format
    """
    @_machine_state_change
    def load_name(self):
        with self._board_context, self._board_condition:
            try:
                return self._interface.digitizer_load_digitizer_name_from_eeprom(
                    self._board)
            except UnicodeDecodeError:
                # This error will occur on new machines which have all
                # 0xFF bytes in EEPROM
                raise conveyor.error.DigitizerNameDecodeError

    """
    Save UTF-8 encoded Digitizer name to EEPROM
    """
    @_machine_state_change
    def save_name(self, name):
        with self._board_context, self._board_condition:
            return self._interface.digitizer_save_digitizer_name_to_eeprom(
                self._board, name)

    """
    Get platform-specific device path string for the camera
    """
    def digitizer_camera_device_path(self):
        return self._camera_device_path

    def _is_calibrated(self):
        return all([self._camera_intrinsics, self._turntable_extrinsics,
            self._left_laser_extrinsics, self._right_laser_extrinsics])

    def register_jog_job_callbacks(self, job):
        def cancel_callback(job):
            self._do_jog = False
        job.cancelevent.attach(cancel_callback)

    @_machine_state_change
    def jog(self, steps, resolution, job):
        self._log.debug("Jogging %s", self.name)
        self._do_jog = True
        try:
            with self._board_context:
                for i in range(steps):
                    if self._state == conveyor.machine.MachineState.DISCONNECTED:
                        raise conveyor.error.MachineDisconnectError
                    elif not self._do_jog:
                        raise conveyor.error.StopScannerJogError
                    self._turntable_job(resolution, 1)
            job.end(True)
        except conveyor.error.StopScannerJogError:
            pass
        except Exception as e:
            exc = conveyor.util.exception_to_failure(e)
            self._log.info("handled error %s", exc)
            job.fail(exc)

    @_machine_state_change
    def query(self):
        with self._board_context:
            info = {}
            camera_state = ctypes.c_bool()
            with self._board_condition:
                self._interface.check_camera(self._board, camera_state)
                self._board_condition.notify_all()
            info['camera'] = camera_state.value
            for laser in self._laser_map:
                state = ctypes.c_bool()
                with self._board_condition:
                    self._interface.check_laser(
                        self._board,self._laser_map[laser],state)
                    self._board_conditionnotify_all()
                info[laser] = state.value
        return info

    def _calibrate_component(self, param_dict, func_dict):
        """
        Calibrates a component.  Uses several dictionary to act as context objects
        that are passed between functions.  Generally, these calibration routines
        have this sort of behavior:
            * jog and capture images
            * process each image

        TODO: There is a boat load of shared code between this and the scan
        function.  They have virtually the same set up and tear down logic.  We
        can collapse them together; its only a matter of how.
        """
        self._log.info("Beginning %s calibration for %s",
            param_dict["component"], self.name)
        def cancel_callback(job):
            # This is done in a cancel callback to allow the client
            # to take control of the camera immediately
            self._destroy_camera()
        param_dict["job"].cancelevent.attach(cancel_callback)
        with self._camera_context, self._board_context:
            try:
                self._motor_lock(True)
                for joblet in self._calibrate_component_implementation(
                        param_dict, func_dict):
                    if (param_dict["job"].state != conveyor.job.JobState.RUNNING or self._stop):
                        break
            except conveyor.error.DigitizerException as e:
                error_string = conveyor.util.exception_to_failure(e)
                self._log.info("Handled exception %s" % (error_string),
                    exc_info=True)
                param_dict["job"].fail(error_string)
            except Exception as e:
                error_string = conveyor.util.exception_to_failure(e)
                self._log.info("Unhandled exception %s" % (error_string),
                    exc_info=True)
                param_dict["job"].fail(error_string)
                raise e
            finally:
                self._motor_lock(False)
                func_dict["destroy_calib"](param_dict["calib"])
                if param_dict["job"].state == conveyor.job.JobState.RUNNING:
                    param_dict["job"].end(None)

    """
    Save the image to the archive directory
    """
    def _archive_image(self, image, archive_path, component, iteration):
        file_name = ('{component}_{iteration:04}.png'.format(
                component=component, iteration=iteration))
        path = os.path.join(archive_path, file_name)
        self._log.debug("Archiving %s image: %s", component, path)
        self._interface.image_save(image, path)

    """
    Jog turntable and capture image for each step. Convert all images to
    grayscale. Archive if specified.
    """
    def _jog_and_capture_grayscale_image(self, param_dict, logging_dict):
        for step in range(param_dict["sector_size"]):
            img = self._interface.create_image()
            yield self._camera_grab(self._camera, img)
            img_gray = self._interface.create_image()
            self._interface.digitizer_image_grayscale(img, img_gray)
            self._interface.matrix_destroy(img)
            logging_dict["image_count"] += 1
            param_dict["images"].append(img_gray)
            # Save the image if archive is enabled
            if param_dict["archive"]:
                self._archive_image(img_gray, param_dict["archive_path"],
                    "%s_calibration_%i" % (param_dict["component"],
                    logging_dict["current_sector"]), step)
            yield self._turntable_jog(param_dict["rotation_resolution"], 1)
            logging_dict["steps_taken"] += 1

    def _calibrate_component_implementation(self, param_dict, func_dict):
        """
        Jog and capture images, then search images in sectors for checkerboard
        pattern. At least a certain number of images for which the pattern is
        found is needed to calibrate. Calibration will not be accepted if error
        is above a certain threshold specified by _calib_error_threshold.
        """
        yield self._camera_set_exposure_with_reinit(0,
            autoexposure=True)
        param_dict['progress'] = {
            "name": "%s calibration" % param_dict["component"],
            "progress": 0}
        logging_dict = {
            "success_count": 0,
            "image_count": 0,
            "steps_taken": 0,
            "found_images": 'none',
            "current_sector": 0,
            "image_grab_progress": 0,
            "search_progress": 0}
        for joblet in func_dict["get_and_add_images"](param_dict, func_dict,
                logging_dict):
            yield joblet
        calib_error = ctypes.c_float()
        # camera_intrinsics_create apparently does not like being done outside
        # of here...
        func_dict["create_extrinsics"](param_dict["extrinsics"])
        if logging_dict["success_count"] < param_dict["min_good_images"]:
            raise conveyor.error.NotEnoughGoodCalibrationImagesError
        func_dict["calibrate"](param_dict["calib"],
            param_dict["extrinsics"], calib_error)
        self._log.info("Calibration error: %.5f", calib_error.value)
        if calib_error.value > param_dict["error_threshold"]:
            raise conveyor.error.CalibrationFailedError

    def _calib_camera_get_and_add_images(self, param_dict, func_dict,
            logging_dict):
        """
        Jog and grab images in a single continuous rotation, then separate the
        set of images into sectors and analyze them. Refer to
        calib_turntable_get_and_add_images for search logic.
        """
        # This does one continuous rotation; it's done in sectors so that archive
        # numbers will match up with log numbers...
        for logging_dict["current_sector"] in range(param_dict["num_sectors"]):
            for joblet in self._jog_and_capture_grayscale_image(param_dict,
                    logging_dict):
                yield joblet
                logging_dict["image_grab_progress"] = (logging_dict["steps_taken"] *
                    param_dict["percent_per_step"])
                percent = self._calculate_progress(logging_dict)
                if percent != param_dict["progress"]["progress"]:
                    # A bit weird, but we keep the progress dict nested in the
                    # param_dict context object.
                    # We want to clamp the percent done to 50
                    param_dict["progress"]["progress"] = percent
                    yield param_dict["job"].heartbeat(param_dict["progress"])
        total_images = param_dict["images"]
        logging_dict["current_sector"] = 0
        """
        param_dict["images"] will hold the list of images to be searched.
        in camera calibration, only a section (one sector) of the total
        images will be searched at a time.
        """
        while logging_dict["current_sector"] < param_dict["num_sectors"]:
            sector_start = (logging_dict["current_sector"] *
                param_dict["sector_size"])
            sector_end = ((logging_dict["current_sector"] + 1) *
                param_dict["sector_size"])
            param_dict["images"] = total_images[sector_start : sector_end]
            logging_dict["found_images"] = 'none'
            # The latter 50 percent of progress consists of searching the taken
            # images for the checkerboard pattern.
            for num_images in self._search_images(param_dict, func_dict,
                    logging_dict):
                logging_dict["search_progress"] += param_dict["percent_per_step"]
                percent = self._calculate_progress(logging_dict)
                if percent != param_dict["progress"]["progress"]:
                    param_dict["progress"]["progress"] = percent
                    yield param_dict["job"].heartbeat(param_dict["progress"])
            if logging_dict["found_images"] == 'front':
                self._log.debug("Successful images found in front of sector %i.",
                    logging_dict["current_sector"])
                if logging_dict["current_sector"] == 0:
                    last_sector = param_dict["num_sectors"] - 1
                    logging_dict["search_progress"] = (
                        last_sector * 100.0/param_dict["num_sectors"])
                    logging_dict["current_sector"] = last_sector - 1
                    self._log.debug("Checking sector %i", last_sector)
                else:
                    break
            elif logging_dict["found_images"] == 'back':
                self._log.debug("Successful images found in back of sector %i.",
                    logging_dict["current_sector"])
            else:
                self._log.debug("No successful images found in sector %i.",
                    logging_dict["current_sector"])
            logging_dict["current_sector"] += 1
            # After finishing search for a sector, update progress accordingly
            # (the whole sector is considered to have been 'searched' regardless
            # of how many were skipped)
            logging_dict["search_progress"] = (logging_dict["current_sector"] *
                100.0 / param_dict["num_sectors"])
            percent = self._calculate_progress(logging_dict)
            param_dict["progress"]["progress"] = percent

        map(self._interface.matrix_destroy, param_dict["images"])

    def _calib_turntable_get_and_add_images(self, param_dict, func_dict,
            logging_dict):
        """
        For each sector, jog and grab images, then analyze images. It is assumed
        that images for which the checkerboard pattern is visible will be spread
        across two sectors-- the back of one, and the front of the following one
        (the first sector being the one that follows the last).

        If images for which the checkerboard pattern is found appear in the front
        of the first sector (sector 0), after getting all the valid images in that
        sector, jog to the last sector and continue search without searching the
        sectors in between.

        If valid images are found in the front of a sector other than the first,
        it is assumed valid images were found in the back of the preceding sector
        as well, and that after getting all the valid images in the sector, no more
        valid images will be found after it.

        If valid images are found in the back of a sector, continue to search next
        sector after getting all valid images.

        If no valid images are found in a sector, continue to search next sector.
        """
        logging_dict["current_sector"] = 0
        while logging_dict["current_sector"] < param_dict["num_sectors"]:
            logging_dict["found_images"] = 'none'
            for joblet in self._jog_and_capture_grayscale_image(param_dict,
                    logging_dict):
                yield joblet
                logging_dict["image_grab_progress"] = (logging_dict["steps_taken"] *
                    param_dict["percent_per_step"])
                percent = self._calculate_progress(logging_dict)
                if percent != param_dict["progress"]["progress"]:
                    # A bit weird, but we keep the progress dict nested in the
                    # param_dict context object.
                    param_dict["progress"]["progress"] = percent
                    yield param_dict["job"].heartbeat(param_dict["progress"])

            for joblet in self._search_images(param_dict, func_dict,
                    logging_dict):
                logging_dict["search_progress"] += param_dict["percent_per_step"]
                percent = self._calculate_progress(logging_dict)
                if percent != param_dict["progress"]["progress"]:
                    param_dict["progress"]["progress"] = percent
                    yield param_dict["job"].heartbeat(param_dict["progress"])
            # After finishing search for a sector, update progress accordingly
            # (the whole sector is considered to have been 'searched' regardless
            # of how many were skipped)
            logging_dict["search_progress"] = (logging_dict["steps_taken"] *
                param_dict["percent_per_step"])
            percent = self._calculate_progress(logging_dict)
            param_dict["progress"]["progress"] = percent

            map(self._interface.matrix_destroy, param_dict["images"])
            param_dict["images"] = []

            if logging_dict["found_images"] == 'front':
                self._log.debug("Successful images found in front of sector %i.",
                    logging_dict["current_sector"])
                if logging_dict["current_sector"] == 0:
                    # Will not search sectors in between.
                    # Update progresses accordingly.
                    last_sector = param_dict["num_sectors"] - 1
                    self._log.debug("Moving to sector %i", last_sector)
                    # jog half a rotation, to the last sector
                    # (assumes that the sector size is 1/4 a rotation)
                    logging_dict["current_sector"] += last_sector - 1
                    yield self._turntable_jog(2, 1)
                    logging_dict["search_progress"] = (
                        last_sector * 100.0/param_dict["num_sectors"])
                    logging_dict["image_grab_progress"] = (
                        last_sector * 100.0/param_dict["num_sectors"])
                    percent = self._calculate_progress(logging_dict)
                    param_dict["progress"]["progress"] = percent
                    yield param_dict["job"].heartbeat(param_dict["progress"])
                    logging_dict["steps_taken"] += (logging_dict["current_sector"] *
                        param_dict["sector_size"])
                else:
                    param_dict["progress"]["progress"] = 100.0
                    yield param_dict["job"].heartbeat(param_dict["progress"])
                    break
            elif logging_dict["found_images"] == 'back':
                self._log.debug("Successful images found in back of sector %i.",
                    logging_dict["current_sector"])
            else:
                self._log.debug("No successful images found in sector %i.",
                    logging_dict["current_sector"])
            logging_dict["current_sector"] += 1

    def _search_images(self, param_dict, func_dict, logging_dict):
        """
        Generator object.  This function yields the number of images it
        analyzes.

        Search the back and front of given list of images for checkerboard
        pattern. If the pattern is found in an image, continue search from that
        direction. If more bad images (ie. ones for which the pattern is not
        seen) are found than allowed is allowed by _fail_count_to_skip, exit
        and continue on to the next sector. Once an image has been searched,
        remove its index from the search list so that add_image is not done on
        the same image more than once if search continues to _add_images.
        """
        self._log.debug("Searching images in sector %i",
            logging_dict["current_sector"])
        indices = range(len(param_dict["images"]))
        failed_count = 0
        for num_tries in range(len(param_dict["images"])/2):
            for index in [indices[-1], indices[0]]:
                try:
                    yield 1
                    func_dict["add_image"](param_dict["calib"],
                        param_dict["images"][index])
                    logging_dict["success_count"] += 1
                    self._log.debug("Pattern found for image %i in sector %i.",
                        index, logging_dict["current_sector"])
                    indices.remove(index)
                    if index > len(param_dict["images"])/2:
                        logging_dict["found_images"] = 'back'
                        indices = indices[::-1]
                    else:
                        logging_dict["found_images"] = 'front'
                        if logging_dict["current_sector"] != 0:
                            # If valid images found in front of a sector other than
                            # the first, current sector will be the last to be searched.
                            # Update progress accordingly.
                            logging_dict["search_progress"] = (
                                (param_dict["num_sectors"] - 1) *
                                100.0/param_dict["num_sectors"])
                            if param_dict["component"] == 'turntable':
                                logging_dict["image_grab_progress"] = 100
                    for num_images in self._add_images(param_dict, func_dict,
                            logging_dict, indices):
                        yield 1
                    break
                except conveyor.error.DigitizerPatternNotFoundException:
                    failed_count += 1
                    self._log.debug("Pattern NOT found for image %i in sector %i.",
                        index, logging_dict["current_sector"])
                    indices.remove(index)
            if (logging_dict["found_images"] != 'none' or
                    failed_count > self._calib_fail_count_to_skip):
                break

        self._log.debug("Took %i images (%i succeeded)",
                logging_dict["image_count"],
                logging_dict["success_count"])

    def _add_images(self, param_dict, func_dict, logging_dict, search_range):
        """
        For an image in a given list of images, do add_image until a certain
        number of consecutive bad images are found.
        """
        self._log.debug("Continuing search from %s of sector...",
            logging_dict["found_images"])
        failed_count = 0
        for index in search_range:
            try:
                yield 1
                func_dict["add_image"](param_dict["calib"],
                    param_dict["images"][index])
                logging_dict["success_count"] += 1
                self._log.debug("Pattern found for image %i in sector %i",
                    index, logging_dict["current_sector"])
                failed_count = 0
            except conveyor.error.DigitizerPatternNotFoundException:
                failed_count += 1
                self._log.debug("Pattern NOT found for image %i in sector %i.",
                        index, logging_dict["current_sector"])
                if failed_count > self._calib_fail_count_to_skip:
                    break

    def _calculate_progress(self, logging_dict):
        # Calculate overall progress percentage. Image grabbing and image searching
        # each make of 50% of the overall progress.
        return int((logging_dict["image_grab_progress"] +
            logging_dict["search_progress"]) / 2)

    def _make_calibration_param_dict(self, param_dict, component):
        component_params = {
            "component": component,
            "rotation_resolution": self._calib_resolution[component],
            "num_sectors": self._calib_num_sectors[component],
            "sector_size": (self._calib_resolution[component] /
                self._calib_num_sectors[component]),
            "min_good_images": self._calib_min_good_images[component],
            "error_threshold": self._calib_error_threshold[component],
            "percent_per_step": 100.0 / self._calib_resolution[component],
            "images": []
        }
        param_dict.update(component_params)

    @_machine_state_change
    def calibrate_turntable(self, job, archive, archive_path):
        """
        Calibrates the turntable.  This happens in stages, since we could
        potentially load too many images into memory.  Uses the
        calibrate_component helper function to execute.
        """
        # We do this in a try/except block to have the job fail logic
        try:
            if archive_path is None and (archive):
                raise conveyor.error.CannotArchiveException
            if not self._camera_calibrated:
                raise conveyor.error.CameraNotCalibratedError
        except Exception as e:
            job.fail(conveyor.util.exception_to_failure(e))
            raise e

        calib = ctypes.c_void_p()
        new_turntable_extrinsics = ctypes.c_void_p()
        self._interface.turntable_calibration_create(calib)
        self._interface.turntable_calibration_set_params(calib,
            self._camera_intrinsics)

        param_dict = {
            "calib": calib,
            "extrinsics": new_turntable_extrinsics,
            "job": job,
            "archive": archive,
            "archive_path": archive_path
        }
        self._make_calibration_param_dict(param_dict, 'turntable')

        func_dict = {
            "add_image": self._interface.turntable_add_image,
            "calibrate": self._interface.turntable_calibrate,
            "create_extrinsics": self._interface.turntable_extrinsics_create,
            "destroy_calib": self._interface.turntable_calibration_destroy,
            "get_and_add_images": self._calib_turntable_get_and_add_images
        }
        try:
            self._calibrate_component(param_dict, func_dict)
        except Exception as e:
            raise e
        else:
            # Only if the above code gets executed do we want to assign the
            # calibration object, otherwise we keep our old one
            if job.conclusion == conveyor.job.JobConclusion.ENDED:
                self._interface.turntable_extrinsics_destroy(self._turntable_extrinsics)
                self._turntable_extrinsics = new_turntable_extrinsics
    
    @_machine_state_change
    def calibrate_camera(self, job, archive, archive_path):
        """
        Calibrates the camera.  Collects images first, then processes them.
        Uses the calibrate_component function to help execute.
        """
        try:
            if archive_path is None and archive:
                raise conveyor.error.CannotArchiveException
        except Exception as e:
            job.fail(conveyor.util.exception_to_failure(e))
            raise e

        calib = ctypes.c_void_p()
        self._interface.camera_calibration_create(calib)
        new_camera_intrinsics = ctypes.c_void_p()

        param_dict = {
            "calib": calib,
            "extrinsics": new_camera_intrinsics,
            "job": job,
            "archive": archive,
            "archive_path": archive_path
        }
        self._make_calibration_param_dict(param_dict, 'camera')

        func_dict = {
            "add_image": self._interface.camera_add_image,
            "calibrate": self._interface.camera_calibrate,
            "create_extrinsics": self._interface.camera_intrinsics_create,
            "destroy_calib": self._interface.camera_calibration_destroy,
            "get_and_add_images": self._calib_camera_get_and_add_images
        }
        try:
            self._calibrate_component(param_dict, func_dict)
        except Exception as e:
            raise e
        else:
            # Only if the above code gets executed do we want to assign the
            # calibration object, otherwise we keep our old one
            if job.conclusion == conveyor.job.JobConclusion.ENDED:
                self._interface.camera_intrinsics_destroy(self._camera_intrinsics)
                self._camera_intrinsics = new_camera_intrinsics
                self._camera_calibrated = True

    def _motor_lock(self, lock):
        """
        Locks the motor
        """
        with self._board_context, self._board_condition:
            self._interface.motor_lock(self._board, lock)

    @_machine_state_change
    def scan(self, job, point_data, rotation_resolution,
            exposure, intensity_threshold, laserline_peak,
            laser, archive, output_left_right, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius, archive_path):
        """
        Scans an object and saves its data to an internally held point_cloud
        object.  That point_cloud data can later be retrieved and meshed into
        a mesh object (which can then be saved as an STL.
        """
        self._log.info('Beginning %s laser scan for %s',
            laser, self.name)
        def cancel_callback(job):
            # This is done in a cancel callback to allow the client
            # to take control of the camera immediately
            self._log.info("Destroying camera in the cancel callback to support the UI.")
            self._destroy_camera()
        job.cancelevent.attach(cancel_callback)
        try:
            if not self._is_calibrated():
                raise conveyor.error.CalibrationNotCompleteError
            if None is archive_path and (archive or output_left_right):
                raise conveyor.error.CannotArchiveException
        except Exception as e:
            job.fail(conveyor.util.exception_to_failure(e))
            raise e
        # Initialization
        bg_image = self._interface.create_image()
        self.capture_background('none', bg_image)

        profile_algorithm = ctypes.c_void_p()
        self._interface.profile_create(profile_algorithm)
        # Create params dict
        param_dict = {
            "profile_points": self._interface.create_vector(),
            "profile_normals": self._interface.create_vector(),
            "point_data": point_data,
            "profile_algorithm": profile_algorithm,
            "image": self._interface.create_image(),
            "bg_image": bg_image,
            "rotation_resolution": rotation_resolution,
            "exposure": exposure,
            "intensity_threshold": intensity_threshold,
            "archive": archive,
            "output_left_right": output_left_right,
            "bounding_cylinder_top": bounding_cylinder_top,
            "bounding_cylinder_bottom": bounding_cylinder_bottom,
            "bounding_cylinder_radius": bounding_cylinder_radius,
            "lasers": self._parse_lasers(laser),
            "laser": laser,
            "job": job,
            "archive_path": archive_path
        }

        # Implementation
        try:
            with self._camera_context, self._board_context:
                self._camera_insert_delay()
                self._motor_lock(True)
                for joblet in self._scan_implementation(param_dict):
                    if param_dict['job'].state != conveyor.job.JobState.RUNNING or self._stop:
                        break
                self._motor_lock(False)
        except conveyor.error.DigitizerException as e:
            error_string = conveyor.util.exception_to_failure(e)
            self._log.info("Handled exception %s" % (error_string),
                exc_info=True)
            job.fail(error_string)
        except Exception as e:
            error_string = conveyor.util.exception_to_failure(e)
            self._log.info("Unhandled exception %s" % (error_string),
                exc_info=True)
            job.fail(error_string)
        finally:
            self.toggle_laser(False, laser)
            # Cleanup
            self._interface.destroy_vectors(
                param_dict["profile_points"],
                param_dict["profile_normals"],
            )
            self._interface.profile_destroy(param_dict["profile_algorithm"])
            self._interface.matrix_destroy(param_dict["image"])
            self._interface.matrix_destroy(param_dict["bg_image"])

        if param_dict["job"].state == conveyor.job.JobState.RUNNING:
            param_dict["job"].end(None)

    def _scan_implementation(self, param_dict):
        # See super long comment below about the camera and race conditions
        with self._camera_condition:
            if param_dict["job"].state != conveyor.job.JobState.STOPPED:
                yield self._camera_set_exposure_with_reinit(
                    param_dict["exposure"])
            else:
                yield 0
        for l in param_dict["lasers"]:
            param_dict['current_laser'] = l
            for joblet in self._scan_with_laser(param_dict):
                yield joblet

    def _scan_with_laser(self, param_dict):
        self._log.debug('Scanning with %s laser for %s',
            param_dict['current_laser'], self.name)
        # Initialization
        progress = {
            "name": "%s_scan" %(param_dict['current_laser']),
            "progress": 0,
            "points": [],
        }
        self.toggle_laser(True, param_dict["current_laser"])
        point_data = param_dict['point_data']
        point_cloud = point_data.get_cloud(param_dict['current_laser'])
        point_cloud.points = self._interface.create_vector()
        point_cloud.normals = self._interface.create_vector()
        laser_intrinsics = getattr(self,
            '_%s_laser_extrinsics' % param_dict['current_laser'])
        self._interface.profile_set_params(param_dict["profile_algorithm"],
            self._camera_intrinsics, self._turntable_extrinsics,
            laser_intrinsics, param_dict["bg_image"],
            param_dict["intensity_threshold"])
        # Scan Implementation
        for i in range(param_dict['rotation_resolution']):
            start_time = datetime.datetime.now()
            # We take the camera condition here (even though _camera_grab
            # takes it as well) to eliminate the race condition with cancel.
            # Consider:
            #   * scanning
            #   * cancel
            #       * camera destruction takes the camera mutex
            #   * during normal scan, _camera_grab waits on the camera mutex
            #   * cancel destroys the camera, releases the mutex
            #   * _camera_grab now takes the mutex, but fails since the camera
            #       is None
            # By taking the condition first the checking if the camera is None,
            # we eliminate this race condition.  We also check if the job
            # has been stopped.  If it is stopped, we dont grab the image and
            # wait for the While loop's condition to break us out of the scan.
            # Otherwise, we continue as normal
            # <3 the night intractable of threading in conveyor
            with self._camera_condition:
                if param_dict["job"].state != conveyor.job.JobState.STOPPED:
                    yield self._camera_grab(self._camera, param_dict['image'])
                else:
                    # HACKY: We yield here to return from the generator and
                    # let the while's loops logic take over.  Otherwise we
                    # would go full speed ahead into profile_extract and fail.
                    yield 0
            yield self._interface.profile_extract(
                param_dict['profile_algorithm'],
                param_dict['image'], param_dict['profile_points'],
                param_dict['profile_normals'], i,
                param_dict['rotation_resolution'])
            for total, profile in zip(
                    (point_cloud.points, point_cloud.normals),
                    (param_dict["profile_points"],
                    param_dict["profile_normals"])):
                self._interface.vector_append(total, profile)

            stop_time = datetime.datetime.now()
            #next line for debugging. commenting out for less log clutter
            #self._log.info("Time from start of loop to jog: %i",
            #    ((stop_time - start_time).microseconds))
            #sleep so that each step takes roughly the same length of time
            if (stop_time - start_time).microseconds < self._delay_time:
                #also for debugging.
                #self._log.info("Sleeping for %i us" % (self._delay_time -
                #    (stop_time - start_time).microseconds))
                time.sleep((self._delay_time -
                    (stop_time-start_time).microseconds) * 1e-6)

            yield self._turntable_jog(param_dict["rotation_resolution"], 1)
            if param_dict["archive"]:
                self._archive_image(
                    param_dict["image"],
                    param_dict["archive_path"],
                    'scan_' + param_dict["current_laser"],
                    i)
            percent = int(i / float(param_dict["rotation_resolution"]) * 100)
            progress["progress"] = percent
            progress["points"] = self._marshall_points(param_dict)
            # There seems to be a race condition here with stopping the job
            # and executing a heartbeat on said job.  This causes a transition
            # error
            yield param_dict["job"].heartbeat(progress)
        # Cleanup
        self.toggle_laser(False, param_dict["current_laser"])
        yield self._remove_points_outside_cylinder(param_dict)
        if param_dict["output_left_right"]:
            root_output, root_ext = os.path.splitext(param_dict["archive_path"])
            filepath = "%s/%s.xyz" % (root_output, param_dict['current_laser'])
            self._log.info("Outputting %s scan to %s",
                param_dict["current_laser"], filepath)
            self._interface.points_save(point_cloud.points,
                point_cloud.normals, filepath)

    def _remove_points_outside_cylinder(self, param_dict):
        """
        reduces points in point cloud that are outside of cylinder
        """
        self._log.debug("Removing points outside of cylinder")
        point_data = param_dict['point_data']
        point_cloud = point_data.get_cloud(param_dict['current_laser'])
        self._interface.remove_outside_cylinder(point_cloud.points,
            point_cloud.normals, param_dict['bounding_cylinder_top'],
            param_dict['bounding_cylinder_bottom'],
            param_dict['bounding_cylinder_radius'])

    def _parse_lasers(self, laser):
        if laser == 'both':
            lasers = self._laser_map.keys()
        elif laser == 'none':
            lasers = []
        elif laser in self._laser_map:
            lasers = [laser]
        else:
            raise conveyor.error.UnknownLaserError
        return lasers

    def _marshall_points(self, param_dict):
        """
        Serialize internal point/normal data into a Python list

        The internal library data is formatted into a list of points,
        where each point is itself a list containing six elements (the
        three point components followed by the three normal
        components).
        """
        # Get point and normal vector data/lengths
        figures = 2
        points_data = ctypes.pointer(ctypes.POINTER(ctypes.c_float)())
        normals_data = ctypes.pointer(ctypes.POINTER(ctypes.c_float)())
        points_size = ctypes.c_int()
        normals_size = ctypes.c_int()
        self._interface.vector_get_data(param_dict['profile_points'],
            points_size, points_data)
        self._interface.vector_get_data(param_dict['profile_normals'],
            normals_size, normals_data)

        # Point and normal vectors should have the same size
        if points_size.value != normals_size.value:
            raise conveyor.error.PointsAndNormalsLengthMismatch(
                points_size.value, normals_size.value)

        c_data_index = 0
        output = []
        for i in range(points_size.value):
            output_point = []
            output_normal = []
            for i in range(3):
                output_point.append(round(points_data[0][c_data_index],
                    figures))
                output_normal.append(round(normals_data[0][c_data_index],
                    figures))
                c_data_index += 1

            output.append(output_point + output_normal)

        return output




class _DigitizerProfile(conveyor.machine.Profile):

    @staticmethod
    def create(name, driver, digitizer_profile):
        digitizer_profile = _DigitizerProfile(name, driver, digitizer_profile)
        return digitizer_profile

    def __init__(self, name, driver, digitizer_profile):
        conveyor.machine.Profile.__init__(self, name, driver, 
            None, None, None, None, None, None, None)
        self._digitizer_profile = digitizer_profile
        self._resolutions = self._digitizer_profile['resolutions']
        self._camera_port = '/dev/ttyACM0'

    def _check_port(self, port):
        result = (port.machine_name['vid'] in self._digitizer_profile['VID']
            and port.machine_name['pid'] in self._digitizer_profile['PID'])
        return result

class Mesher(object):
    """
    Meshing object is a state machine designed to take the mesh through
    all stages of post processing.  The meshing object can only modify
    one mesh at a time.  Calls to "initialize_mesh" will transition
    the state machine to the start state.
    """
    def __init__(self, config):
        self._log = conveyor.log.getlogger(self)
        self._config = config
        self._interface = _DigitizerLibraryInterface(self._config)
        self._meshes = {}
        self._id = 0
        self._mesh_id_condition = threading.Condition()
        self._mesh_condition = threading.Condition()

    def check_mesh_id(func):
        def decorator(*args, **kwargs):
            try:
                func(*args, **kwargs)
            except KeyError:
                raise conveyor.error.UnknownMeshIdException
        return decorator

    def destroy_all_meshes(self):
        """
        NB: We iterate over the keys in self._meshes so we don't change
        dict size during iteration.
        """
        with self._mesh_condition:
            map(self.destroy_mesh, self._meshes.keys())

    def _create_mesh_id(self):
        with self._mesh_id_condition:
            id = self._id
            self._id += 1
        return id

    def create_mesh(self):
        mesh_id = self._create_mesh_id()
        self._log.debug("Creating mesh %i", mesh_id)
        with self._mesh_condition:
            self._meshes[mesh_id] = self._interface.create_mesh()
        return mesh_id

    @check_mesh_id
    def destroy_mesh(self, mesh_id):
        self._log.debug("Destroying mesh with id: %i", mesh_id)
        with self._mesh_condition:
            self._interface.mesh_destroy(self._meshes[mesh_id])
            self._meshes.pop(mesh_id)

    def deep_copy(self, mesh_src_id, mesh_dst_id):
        self._log.debug(
            "Deep-copying mesh %i into mesh %i",
            mesh_src_id, mesh_dst_id)
        with self._mesh_condition:
            self._interface.mesh_copy(
                self._meshes[mesh_src_id],
                self._meshes[mesh_dst_id])

    @check_mesh_id
    def poisson_reconstruction(self, mesh_id, point_data,
            max_octree_depth,min_octree_depth, solver_divide, iso_divide,
            min_samples, scale, manifold):
        self._log.info("Poisson reconstructing mesh: %i", mesh_id)
        cloud = point_data.get_cloud_to_save()
        points = cloud.points
        normals = cloud.normals
        with self._mesh_condition:
            self._interface.poisson_reconstruction(points, normals,
                self._meshes[mesh_id], min_octree_depth, max_octree_depth,
                solver_divide, iso_divide, min_samples, scale, manifold)
            self._interface.cut_bounding_box(points, self._meshes[mesh_id], 1.0)
            #self._interface.place_on_platform(self._meshes[mesh_id])

    @check_mesh_id
    def cut_plane(self, mesh_id, x_normal, y_normal, z_normal,
            plane_origin):
        self._log.info("Cutting mesh with x: %i y: %i z: %i origin: %f",
            x_normal, y_normal, z_normal, plane_origin)
        with self._mesh_condition:
            self._interface.cut_plane(self._meshes[mesh_id], x_normal,
                y_normal, z_normal, plane_origin)

    @check_mesh_id
    def place_on_platform(self, mesh_id):
        self._log.info("Placing mesh on platform")
        with self._mesh_condition:
            self._interface.place_on_platform(self._meshes[mesh_id])

    @check_mesh_id
    def save_mesh(self, mesh_id, output_file):
        self._log.info("Saving mesh %i to %s", mesh_id, output_file)
        with self._mesh_condition:
            self._interface.mesh_save(self._meshes[mesh_id], output_file)

    @check_mesh_id
    def load_mesh(self, mesh_id, input_file):
        self._log.info("Loading mesh %i from %s", mesh_id, input_file)
        with self._mesh_condition:
            self._interface.mesh_load(self._meshes[mesh_id], input_file)

class _DigitizerLibraryInterface(object):
    def __init__(self, config):
        self._lib = config.get("digitizer", "digitizer_library")

    def check_result(func):
        def decorator(*args, **kwargs):
            result = func(*args, **kwargs)
            if result == -1:
                raise conveyor.error.DigitizerException
            elif result == -2:
                raise conveyor.error.DigitizerArgumentException
            elif result == -3:
                raise conveyor.error.DigitizerCameraNotFoundException
            elif result == -4:
                raise conveyor.error.DigitizerTimeoutException
            elif result == -5:
                raise conveyor.error.DigitizerPatternNotFoundException
            elif result == -6:
                raise conveyor.error.DigitizerInsufficientLaserPointsException
        return decorator

    def create_vector(self):
        vector = ctypes.c_void_p()
        self.vector_create(vector)
        return vector

    def destroy_vectors(self, *args):
        for vector in args:
            self.vector_destroy(vector)

    def create_mesh(self):
        mesh = ctypes.c_void_p()
        self.mesh_create(mesh)
        return mesh

    def create_image(self):
        image = ctypes.c_void_p()
        self.matrix_create(image)
        return image

    @check_result
    def digitizer_reset_into_bootloader(self, board):
        return self._lib.digitizer_reset_into_bootloader(board)

    @check_result
    def digitizer_get_firmware_version(self, board, major, minor, revision):
        return self._lib.digitizer_get_firmware_version(board,
            ctypes.byref(major), ctypes.byref(minor), ctypes.byref(revision))

    @check_result
    def run_mainloop(seconds):
        return self._lib.digitizer_run_mainloop(ctypes.c_double(seconds))

    @check_result
    def board_create(self, port, board):
        return self._lib.digitizer_board_create(
            ctypes.c_char_p(port), ctypes.byref(board))

    @check_result
    def board_destroy(self, board):
        return self._lib.digitizer_board_destroy(board)

    @check_result
    def motor_lock(self, board, lock):
        return self._lib.digitizer_board_stepper_lock(board,
            ctypes.c_bool(lock))

    @check_result
    def jog(self, board, resolution, steps):
        return self._lib.digitizer_board_jog(board, ctypes.c_int(resolution),
            ctypes.c_int(steps))

    @check_result
    def toggle_laser(self, board, laser, enabled):
        return self._lib.digitizer_board_toggle_laser(board,
            ctypes.c_int(laser), ctypes.c_bool(enabled))

    @check_result
    def check_laser(self, board, laser, enabled):
        return self._lib.digitizer_board_check_laser(board, ctypes.c_int(laser),
            ctypes.byref(enabled))

    @check_result
    def toggle_camera(self, board, enabled):
        return self._lib.digitizer_board_toggle_camera(board,
            ctypes.c_bool(enabled))

    @check_result
    def check_camera(self, board, enabled):
        return self._lib.digitizer_board_check_camera(board,
            ctypes.byref(enabled))

    @check_result
    def camera_create(self, usb_info, width, height, camera):
        return self._lib.digitizer_camera_create(
            ctypes.c_int(usb_info.vid),
            ctypes.c_int(usb_info.pid),
            ctypes.c_char_p(usb_info.serial),
            ctypes.c_int(width),
            ctypes.c_int(height),
            ctypes.byref(camera))

    @check_result
    def camera_destroy(self, camera):
        return self._lib.digitizer_camera_destroy(camera)

    @check_result
    def set_camera_exposure(self, camera, exposure, autoexposure=False):
        #doing this because libdigitizer does not check incoming exposure values
        #and anything greater than 1 will give a CameraControl error
        exposure = min(1, exposure)
        return self._lib.digitizer_camera_set_exposure(camera,
            ctypes.c_bool(autoexposure), ctypes.c_float(exposure))

    @check_result
    def camera_grab(self, camera, image, ensure_new=True):
        return self._lib.digitizer_camera_grab(camera, image,
            ctypes.c_bool(ensure_new))

    @check_result
    def capture_background(self, camera, image, frames):
        return self._lib.digitizer_camera_capture_background(camera, image,
            ctypes.c_int(frames))

    @check_result
    def matrix_create(self, matrix):
        return self._lib.digitizer_matrix_create(ctypes.byref(matrix))

    @check_result
    def matrix_destroy(self, matrix):
        return self._lib.digitizer_matrix_destroy(matrix)

    @check_result
    def matrix_invert(self, matrix):
        return self._lib.digitizer_matrix_invert(matrix)

    @check_result
    def image_save(self, matrix, filepath):
        return self._lib.digitizer_image_save(matrix, ctypes.c_char_p(filepath))

    @check_result
    def image_load(self, matrix, filepath):
        return self._lib.digitizer_image_load(matrix, ctypes.c_char_p(filepath))

    @check_result
    def vector_create(self, vector):
        return self._lib.digitizer_vectors_create(ctypes.byref(vector))

    @check_result
    def vector_destroy(self, vector):
        return self._lib.digitizer_vectors_destroy(vector)

    @check_result
    def vector_append(self, vectora, vectorb):
        return self._lib.digitizer_vectors_append(vectora, vectorb)

    @check_result
    def points_merge(self, vectors_a, normals_a, vectors_b, normals_b, radius):
        return self._lib.digitizer_points_merge(vectors_a, normals_a,
            vectors_b, normals_b, radius)

    @check_result
    def vector_get_data(self, vector, length, values):
        return self._lib.digitizer_vectors_get_data(vector,
            ctypes.byref(length), values)

    @check_result
    def points_save(self, points, normals, filepath):
        return self._lib.digitizer_points_save(points, normals,
            ctypes.c_char_p(filepath))

    @check_result
    def points_load(self, points, normals, filepath):
        return self._lib.digitizer_points_load(points, normals,
            ctypes.c_char_p(filepath))

    @check_result
    def points_transform(self, points, normals, matrix):
        return self._lib.digitizer_points_transform(points, normals,
            matrix, ctypes.c_bool(True))

    @check_result
    def remove_outliers_adaptive(self, points, normals, setsize, sigma):
        return self._lib.digitizer_points_remove_outliers_adaptive(points,
            normals, ctypes.c_int(setsize), ctypes.c_float(sigma))

    @check_result
    def remove_outliers_fixed(self, points, normals, setsize, percent):
        return self._lib.digitizer_points_remove_outliers_fixed(points, normals,
            ctypes.c_int(setsize), ctypes.c_float(percent))

    @check_result
    def coarse_align(self, scene_points, scene_normals, model_points, model_normals,
            model_matrix):
        return self._lib.digitizer_points_coarse_align(scene_points, scene_normals,
            model_points, model_normals, model_matrix)

    @check_result
    def fine_align(self, scene, model, scene_matrix, pre_error, post_error,
                   sample_rate, max_samples, inlier_ratio, max_iterations):
        return self._lib.digitizer_points_fine_align(scene, model, scene_matrix,
            ctypes.byref(pre_error), ctypes.byref(post_error),
            ctypes.c_float(sample_rate), ctypes.c_int(max_samples),
            ctypes.c_float(inlier_ratio), ctypes.c_int(max_iterations))

    @check_result
    def downsample(self, points, normals, grid_size):
        return self._lib.digitizer_points_downsample(points, normals,
            ctypes.c_float(grid_size))

    @check_result
    def mesh_create(self, mesh):
        return self._lib.digitizer_mesh_create(ctypes.byref(mesh))

    @check_result
    def mesh_destroy(self, mesh):
        return self._lib.digitizer_mesh_destroy(mesh)

    @check_result
    def mesh_copy(self, mesh_src, mesh_dst):
        return self._lib.digitizer_mesh_copy(mesh_src, mesh_dst)

    @check_result
    def poisson_reconstruction(self, points, normals, mesh, min_octree_depth,
            max_octree_depth, solver_divide, iso_divide, min_samples, scale,
            manifold):
        return self._lib.digitizer_mesh_point_cloud(points, normals, mesh,
            ctypes.c_int(max_octree_depth), ctypes.c_int(min_octree_depth),
            ctypes.c_int(solver_divide), ctypes.c_int(iso_divide),
            ctypes.c_int(min_samples), ctypes.c_float(scale),
            ctypes.c_bool(manifold))

    @check_result
    def fill_holes(self, mesh, max_hole_size=1000000):
        return self._lib.digitizer_fill_holes(
            mesh, ctypes.c_float(max_hole_size))

    @check_result
    def mesh_save(self, mesh, filepath):
        return self._lib.digitizer_mesh_save(mesh, ctypes.c_char_p(filepath))

    @check_result
    def mesh_load(self, mesh, filepath):
        return self._lib.digitizer_mesh_load(mesh, ctypes.c_char_p(filepath))

    @check_result
    def camera_intrinsics_create(self, camera_intrinsics):
        return self._lib.digitizer_camera_intrinsics_create(
            ctypes.byref(camera_intrinsics))

    @check_result
    def camera_intrinsics_destroy(self, camera_intrinsics):
        return self._lib.digitizer_camera_intrinsics_destroy(camera_intrinsics)

    @check_result
    def camera_calibration_create(self, calib):
        return self._lib.digitizer_camera_calibration_create(
            ctypes.byref(calib))

    @check_result
    def camera_calibration_destroy(self, calib):
        return self._lib.digitizer_camera_calibration_destroy(calib)

    @check_result
    def camera_add_image(self, calib, image):
        return self._lib.digitizer_camera_calibration_add_image(calib, image)

    @check_result
    def camera_calibrate(self, calib, camera_intrinsics, error):
        return self._lib.digitizer_camera_calibration_calibrate(calib,
            camera_intrinsics, ctypes.byref(error))

    @check_result
    def camera_calibration_verify(self, calib, camera_intrinsics, image,
            error):
        return self._lib.digitizer_camera_calibration_verify(calib,
            camera_intrinsics, image, ctypes.byref(error))

    @check_result
    def turntable_extrinsics_create(self, turntable_extrinsics):
        return self._lib.digitizer_turntable_extrinsics_create(
            ctypes.byref(turntable_extrinsics))

    @check_result
    def turntable_extrinsics_destroy(self, turntable_extrinsics):
        return self._lib.digitizer_turntable_extrinsics_destroy(
            turntable_extrinsics)

    @check_result
    def turntable_calibration_create(self, calib):
        return self._lib.digitizer_turntable_calibration_create(
            ctypes.byref(calib))

    @check_result
    def turntable_calibration_destroy(self, calib):
        return self._lib.digitizer_turntable_calibration_destroy(calib)

    @check_result
    def turntable_calibration_set_params(self, calib, camera_intrinsics):
        return self._lib.digitizer_turntable_calibration_set_params(calib,
            camera_intrinsics)

    @check_result
    def turntable_add_image(self, calib, image):
        return self._lib.digitizer_turntable_calibration_add_image(calib, image)

    @check_result
    def turntable_calibrate(self, calib, camera_intrinsics, error):
        return self._lib.digitizer_turntable_calibration_calibrate(calib,
            camera_intrinsics, ctypes.byref(error))

    @check_result
    def laser_extrinsics_create(self, laser_extrinsics):
        return self._lib.digitizer_laser_extrinsics_create(
            ctypes.byref(laser_extrinsics))

    @check_result
    def laser_extrinsics_destroy(self, laser_extrinsics):
        return self._lib.digitizer_laser_extrinsics_destroy(laser_extrinsics)

    @check_result
    def laser_calibration_create(self, calib):
        return self._lib.digitizer_laser_calibration_create(ctypes.byref(calib))

    @check_result
    def laser_calibration_destroy(self, calib):
        return self._lib.digitizer_laser_calibration_destroy(calib)

    @check_result
    def laser_calibration_set_params(self, calib, camera_intrinsics,
            laser_threshold, inlier_ratio, max_plane_dist):
        return self._lib.digitizer_laser_calibration_set_params(calib,
            camera_intrinsics, ctypes.c_int(laser_threshold),
            ctypes.c_float(inlier_ratio), ctypes.c_float(max_plane_dist))

    @check_result
    def laser_add_image(self, calib, calibrator_image, laser_image):
        return self._lib.digitizer_laser_calibration_add_image(calib,
            calibrator_image, laser_image)

    @check_result
    def laser_calibrate(self, calib, camera_intrinsics, error):
        return self._lib.digitizer_laser_calibration_calibrate(calib,
            camera_intrinsics, ctypes.byref(error))

    @check_result
    def profile_create(self, profile):
        return self._lib.digitizer_profile_create(ctypes.byref(profile))

    @check_result
    def profile_destroy(self, profile):
        return self._lib.digitizer_profile_destroy(profile)

    @check_result
    def profile_set_params(self, profile, camera_intrinsics,
            turntable_extrinsics, laser_extrinsics, bg_image, laser_threshold):
        return self._lib.digitizer_profile_set_params(profile,
            camera_intrinsics, turntable_extrinsics, laser_extrinsics, bg_image,
            ctypes.c_int(laser_threshold))

    @check_result
    def profile_extract(self, profile, image, points, normals, step_id, steps):
        return self._lib.digitizer_profile_extract(profile, image, points,
            normals, ctypes.c_int(step_id), ctypes.c_int(steps))

    @check_result
    def calibration_save(self, filepath, camera_intrinsics,
            turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics):
        return self._lib.digitizer_setup_save(ctypes.c_char_p(filepath),
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    @check_result
    def calibration_load(self, filepath, camera_intrinsics,
            turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics):
        return self._lib.digitizer_setup_load(ctypes.c_char_p(filepath),
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    @check_result
    def estimate_normals(self, points, normals, neighbors):
        return self._lib.digitizer_points_estimate_normals(points, normals,
             neighbors)

    @check_result
    def remove_outside_cylinder(self, points, normals, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius):
        return self._lib.digitizer_points_remove_outside_of_cylinder(points,
            normals, ctypes.c_float(bounding_cylinder_radius),
            ctypes.c_float(bounding_cylinder_bottom),
            ctypes.c_float(bounding_cylinder_top))

    @check_result
    def cut_bounding_box(self, points, mesh, scale):
        return self._lib.digitizer_mesh_cut_bounding_box(points, mesh,
            ctypes.c_float(scale))

    @check_result
    def cut_plane(self, mesh, x_normal, y_normal, z_normal, plane_origin):
        return self._lib.digitizer_mesh_planar_cut(mesh,
            ctypes.c_float(x_normal), ctypes.c_float(y_normal),
            ctypes.c_float(z_normal), ctypes.c_float(plane_origin))

    @check_result
    def place_on_platform(self, mesh):
        return self._lib.digitizer_mesh_place_on_platform(mesh)

    @check_result
    def points_smooth(self, points, normals, neighbors, iterations,
            smooth_points, smooth_normals):
        return self._lib.digitizer_points_smooth(points, normals,
            ctypes.c_int(neighbors), ctypes.c_int(iterations),
            ctypes.c_bool(smooth_points), ctypes.c_bool(smooth_normals))

    @check_result
    def save_calibration_to_user_eeprom(self, board, camera_intrinsics,
            turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics):
        return self._lib.digitizer_setup_save_to_user_eeprom(board,
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    @check_result
    def save_calibration_to_factory_eeprom(self, board, camera_intrinsics,
            turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics):
        return self._lib.digitizer_setup_save_to_factory_eeprom(board,
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    def digitizer_invalidate_user_calibration(self, board):
        return self._lib.digitizer_invalidate_user_calibration(board)

    @check_result
    def load_calibration_from_user_eeprom(self, board, camera_intrinsics,
            turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics):
        return self._lib.digitizer_setup_load_from_user_eeprom(board,
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    @check_result
    def load_calibration_from_factory_eeprom(self, board,
            camera_intrinsics, turntable_extrinsics,
            left_laser_extrinsics, right_laser_extrinsics):
        return self._lib.digitizer_setup_load_from_factory_eeprom(board,
            camera_intrinsics, turntable_extrinsics, left_laser_extrinsics,
            right_laser_extrinsics)

    @check_result
    def digitizer_save_digitizer_name_to_eeprom(self, board, name):
        self._lib.digitizer_save_digitizer_name_to_eeprom.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p]
        if not isinstance(name, unicode):
            raise TypeError('name must be a Unicode string, got type %s' % (name.__class__.__name__))
        name = name.encode('utf-8')
        if len(name) > 15:
            raise conveyor.error.DigitizerNameTooLongException
        else:
            return self._lib.digitizer_save_digitizer_name_to_eeprom(board, name)

    def digitizer_camera_device_path(self, camera):
        # The libdigitizer C interface does not provide any way to get
        # the actual string length. This should really be fixed in
        # libdigitzer, but for now we just allocate a really big
        # buffer that should always be much larger than needed.
        buf = ctypes.create_string_buffer(1024);

        # It's late in the product cycle, so just to be on the safe
        # side let's avoid any off-by-one length errors and pad the
        # memory we tell libdigitizer about
        safe_size = len(buf) - 8

        if self._lib.digitizer_camera_device_path(camera, safe_size, buf) == 0:
            return buf.value
        else:
            raise conveyor.error.DigitizerException

    def digitizer_load_digitizer_name_from_eeprom(self, board):
        self._lib.digitizer_load_digitizer_name_from_eeprom.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p]

        buf = ctypes.create_string_buffer(16);
        if self._lib.digitizer_load_digitizer_name_from_eeprom(board, buf) != 0:
            raise conveyor.error.DigitizerException
        return buf.value.decode('utf-8')

    @check_result
    def digitizer_image_grayscale(self, color_image, gray_image):
        return self._lib.digitizer_image_grayscale(color_image, gray_image);

