# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/arg.py
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

'''
This module contains functions for configuring argparse with all of the
command-line arguments and options used by both the conveyor client and
service. These functions should be used with the `@args` class decorator.

All of the options are collected here, in one place, to avoid conflicts and
confusion.

'''

from __future__ import (absolute_import, print_function, unicode_literals)

import conveyor.platform


def install(parser, cls):
    '''
    Install into `parser` all of the command-line arguments and options
    registered with the `@args` decorator against class `cls` and its parent
    classes.

    '''

    args_funcs = getattr(cls, '_args_funcs', None)
    if None is not args_funcs:
        for func in args_funcs:
            func(parser)


# Positional Arguments ########################################################

def positional_access_token(parser):
    parser.add_argument(
        'access_token',
        help='Thingiverse access token',
        metavar='ACCESS_TOKEN'
        )

def positional_layout_id(parser):
    parser.add_argument(
        'layout_id',
        help='Digital store layout id',
        metavar='LAYOUT_ID'
        )

def positional_driver(parser):
    parser.add_argument(
        'driver_name',
        help='use DRIVER',
        metavar='DRIVER',
        )


def positional_firmware_version(parser):
    parser.add_argument(
        'firmware_version',
        help='the FIRMWARE-VERSION',
        metavar='FIRMWARE-VERSION',
        )


def positional_input_file(parser):
    parser.add_argument(
        'input_file',
        help='read input from INPUT-FILE',
        metavar='INPUT-FILE',
        )


def positional_job(parser):
    parser.add_argument(
        'job_id',
        type=int,
        help='execute command on JOB',
        metavar='JOB',
        )


def positional_output_file(parser):
    parser.add_argument(
        'output_file',
        help='write output to OUTPUT-FILE',
        metavar='OUTPUT-FILE',
        )


def positional_output_file_optional(parser):
    parser.add_argument(
        'output_file',
        nargs='?',
        help='write output to OUTPUT-FILE',
        metavar='OUTPUT-FILE',
        )


def positional_profile(parser):
    parser.add_argument(
        'profile_name',
        help='use PROFILE',
        metavar='PROFILE',
        )


def positional_axis(parser):
    parser.add_argument(
        'axis',
        help='axis to jog',
        metavar='AXIS',
        )


def positional_distance(parser):
    parser.add_argument(
        'distance_mm',
        type=int,
        help='distance to move in mm',
        metavar='DISTANCE-MM',
        )


def positional_duration(parser):
    parser.add_argument(
        'duration',
        type=int,
        help='Total duration in milliseconds(according to s3g)',
        metavar='TOTAL_DURATION',
        )

# Options #####################################################################

def thingiverse_token(parser):
    parser.add_argument(
        '--thingiverse-token',
        default=None,
        action='store',
        help="Thingiverse token used for setting a thingiverse account on a "
             "birdwing machine",
        metavar="THINGIVERSEI_TOKEN",
        dest="thingiverse_token",
    )

def metadata(parser):
    import json
    parser.add_argument(
        '--metadata',
        action='store',
        default=json.dumps({"origin": "conveyor_command_line_client"}),
        help='Valid json metadata to add to a tinything archive',
        metavar='METADATA',
        dest='metadata',
    )


def thumbnail_dir(parser):
    parser.add_argument(
        '--thumbnail-dir',
        action='store',
        default='./thumbnails',
        help='Thumbnail dir to add to the tinything archive',
        metavar='THUMBNAIL_DIR',
        dest='thumbnail_dir',
    )


def add_start_end(parser):
    parser.add_argument(
        '--add-start-end',
        action='store_true',
        help='add start/end G-code to OUTPUT-PATH',
        dest='add_start_end',
        )


def config(parser):
    parser.add_argument(
        '-c',
        '--config',
        action='store',
        default=conveyor.platform.DEFAULT_CONFIG_FILE,
        type=str,
        required=False,
        help='read configuration from FILE',
        metavar='FILE',
        dest='config_file',
        )

def driver(parser):
    parser.add_argument(
        '-d',
        '--driver',
        action='store',
        default=None,
        type=str,
        required=False,
        help='use DRIVER to control the machine',
        metavar='DRIVER',
        dest='driver_name',
        )

def filepath(parser):
    parser.add_argument(
        '--filepath',
        action='store',
        default=None,
        type=str,
        required=True,
        help='File to post',
        metavar='FILEPATH',
        dest='filepath',
    )

def localpath(parser):
    parser.add_argument(
        '--localpath',
        action='store',
        default=None,
        type=str,
        required=True,
        help='File to get',
        metavar='LOCALPATH',
        dest='localpath',
    )

def remotepath(parser):
    parser.add_argument(
        '--remotepath',
        action='store',
        default=None,
        type=str,
        required=True,
        help='File to get',
        metavar='REMOTEPATH',
        dest='remotepath',
    )

def index(parser):
    parser.add_argument(
        '--index',
        action='store',
        default=0,
        type=int,
        required=True,
        help='Index to Heat',
        metavar='INDEX',
        dest='index',
    ) 

def temperature(parser):
    parser.add_argument(
        '--temperature',
        action='store',
        default=0,
        type=int,
        required=True,
        help='Temperature',
        metavar='TEMPERATURE',
        dest='temperature',
    )

def host_version(parser):
    parser.add_argument(
        '--host-version',
        action='store',
        default='1',
        type=str,
        required=True,
        help='Host Version to send to Embedded Conveyor',
        metavar='HOSTVERSION',
        dest='host_version',
    )

def extruder(parser):
    parser.add_argument(
        '-e',
        '--extruder',
        action='store',
        default='right',
        type=str,
        choices=('left', 'right', 'both',),
        required=False,
        help='use EXTRUDER to print',
        metavar='EXTRUDER',
        dest='extruder_name',
        )

def tool_index(parser):
    parser.add_argument(
        '--tool-index',
        action='store',
        default=0,
        type=int,
        required=False,
        help='Tool index to use',
        metavar='EXTRUDER',
        dest='tool_index',
)

def file_type(parser):
    parser.add_argument(
        '--file-type',
        action='store',
        default='x3g',
        type=str,
        choices=('s3g', 'x3g',),
        required=False,
        help='use the FILE-TYPE format for the OUTPUT-FILE',
        metavar='FILE-TYPE',
        dest='file_type',
        )


def gcode_processor(parser):
    parser.add_argument(
        '--gcode-processor',
        action='append',
        default=None,
        type=str,
        required=False,
        help='run PROCESSOR on .gcode files',
        metavar='PROCESSOR',
        dest='gcode_processor_names',
        )


def has_start_end(parser):
    parser.add_argument(
        '--has-start-end',
        action='store_true',
        help='INPUT-PATH includes custom start/end .gcode',
        dest='has_start_end',
        )


def json(parser):
    parser.add_argument(
        '-j',
        '--json',
        action='store_true',
        help='print output in JSON format',
        dest='json',
        )


def level(parser):
    parser.add_argument(
        '-l',
        '--level',
        action='store',
        default=None,
        type=str,
        choices=('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET',),
        required=False,
        help='set logging to LEVEL',
        metavar='LEVEL',
        dest='level_name',
        )

def client_id(parser):
    parser.add_argument(
        '--client-id',
        action='store',
        type=str,
        required=False,
        help='Client id to authenticate a birdwing machine',
        metavar='CLIENT_ID',
        dest='client_id'
    )

def client_secret(parser):
    parser.add_argument(
        '--client-secret',
        action='store',
        type=str,
        required=False,
        help='Client secret to authenticate a birdwing machine with',
        metavar='CLIENT_SECRET',
        dest='client_secret',
    )
        
def birdwing_code(parser):
    parser.add_argument(
        '--birdwing-code',
        action='store',
        type=str,
        required=False,
        help='Birdwing code used to authenticate the machine',
        metavar='BIRDWING_CODE',
        dest='birdwing_code',
    )

def ip_address(parser):
    parser.add_argument(
        '--ip-address',
        action='store',
        type=str,
        help='IP address of the machine you want to directly connect to.',
        metavar='IP_ADDRESS',
        dest='ip_address',
    )

def machine(parser):
    parser.add_argument(
        '-m',
        '--machine',
        action='store',
        default=None,
        type=str,
        required=False,
        help='execute command on MACHINE',
        metavar='MACHINE',
        dest='machine_name',
        )


def machine_type(parser):
    parser.add_argument(
        '--machine-type',
        action='store',
        default='TheReplicator',
        type=str,
        required=False,
        help='the MACHINE-TYPE',
        metavar='MACHINE-TYPE',
        dest='machine_type',
        )

def pid(parser):
    parser.add_argument(
        '--pid',
        action='store',
        default='0xD314',
        type=str,
        required=False,
        help='the PID',
        metavar='PID',
        dest='pid',
        )


def firmware_version(parser):
    parser.add_argument(
        '--machine-version',
        action='store',
        default='7.0',
        type=str,
        required=False,
        help='the firmware VERSION',
        metavar='VERSION',
        dest='firmware_version',
        )


def profile(parser):
    parser.add_argument(
        '-P',
        '--profile',
        action='store',
        default=None,
        type=str,
        required=False,
        help='use machine PROFILE',
        metavar='PROFILE',
        dest='profile_name',
        )


def nofork(parser):
    parser.add_argument(
        '--nofork',
        action='store_true',
        help='do not fork nor detach from the controlling terminal',
        dest='nofork',
        )


def slicer(parser):
    parser.add_argument(
        '-s',
        '--slicer',
        action='store',
        default='miraclegrue',
        type=str,
        choices=('miraclegrue',),
        required=False,
        help='slice model with SLICER',
        metavar='SLICER',
        dest='slicer_name',
        )


def slicer_settings(parser):
    parser.add_argument(
        '-S',
        '--slicer-settings',
        action='store',
        default=None,
        type=str,
        required=False,
        help='use custom SLICER-SETTINGS-PATH',
        metavar='SLICER-SETTINGS-PATH',
        dest='slicer_settings_path',
        )


def version(parser):
    parser.add_argument(
        '-v',
        '--version',
        action='version',
        help='show the verison message and exit',
        version='%(prog) 1.2.0.0',
        )

def heat_platform(parser):
    parser.add_argument(
        '--heat-platform',
        action='store_true',
        help='determines if the platform will be heated',
        dest='heat_platform',
        )

def username(parser):
    parser.add_argument(
        "--username",
        action="store",
        default = "conveyor",
        type=str,
        required=False,
        help="Username to use when operating a Birdwing Machine",
        metavar="USERNAME",
        dest="username",
    )

def display_name(parser):
    parser.add_argument(
        "--display-name",
        action="store",
        type=str,
        required=False,
        help="New display name for your machine",
        metavar="VANITY_NAME",
        dest="display_name",
    )

def steps(parser):
    parser.add_argument(
        '--steps',
        action='store',
        default=100,
        type=int,
        help='Total number of steps to move a machine',
        metavar='STEPS',
        dest='steps',
    )

def rotation_resolution(parser):
    parser.add_argument(
        '--rotation-resolution',
        action='store',
        default=100,
        choices=(2, 4, 12, 18, 36, 100, 200, 320, 400, 640, 800, 1600, 3200, 20480),
        type=int,
        help='Number of steps to take in a 360-degree scan',
        metavar='ROTATION_RESOLUTION',
        dest='rotation_resolution',
    )

def exposure(parser):
    parser.add_argument(
        '--exposure',
        action='store',
        default=0.0,
        type=float,
        help='Exposure for Digitizer Camera',
        metavar='EXPOSURE',
        dest='exposure',
    )

def intensity_threshold(parser):
    parser.add_argument(
        '--intensity-threshold',
        action='store',
        default=200,
        type=int,
        help='Laser line intensity',
        metavar='INTENSITY_THRESHOLD',
        dest='intensity_threshold',
    )

def laserline_peak(parser):
    parser.add_argument(
        '--laserline-peak',
        action='store',
        default=0,
        type=int,
        help='Which peaks to evaluate from a laser line',
        metavar='LASERLINE_PEAK',
        dest='laserline_peak',
    )

def normal_estimation_radius(parser):
    parser.add_argument(
        '--normal-estimation-radius',
        action='store',
        default=0.0,
        type=float,
        help='Value to help estimate normals',
        metavar='NORMAL_ESTIMATION_RADIUS',
        dest='normal_estimation_radius',
    )

def nearest_neighbors(parser):
    parser.add_argument(
        '--nearest-neighbors',
        action='store',
        default=20,
        type=int,
        help='Size of neighborhood used when culling points.',
        metavar='NEAREST_NEIGHBORs',
        dest='nearest_neighbors'
    )

def adaptive_sigma(parser):
    parser.add_argument(
        '--adaptive-sigma',
        action='store',
        default=2.0,
        type=float,
        help='Specifies which standard deviations determine inlier points.',
        metavar='ADAPTIVE_SIGMA',
        dest='adaptive_sigma',
    )

def fixed_cutoff_percent(parser):
    parser.add_argument(
        '--fixed-cutoff-percent',
        action='store',
        default=0.02,
        type=float,
        help='Percentage of points we determine are outliers and remove.',
        metavar='FIXED_CUTOFF_PERCENT',
        dest='fixed_cutoff_percent',
    )

def archive_mesh(parser):
    parser.add_argument(
        '--archive-mesh',
        action='store_true',
        help='Archive all scan images',
        dest='archive_mesh',
    )

def no_archive_mesh(parser):
    parser.add_argument(
        '--no-archive-mesh',
        action='store_false',
        help='Dont Archive scan images',
        dest='archive_mesh'
    )

def archive_images(parser):
    parser.add_argument(
        '--archive-images',
        action='store_true',
        help='Archive images',
        dest='archive_images'
    )

def no_archive_images(parser):
    parser.add_argument(
        '--no-archive-images',
        action='store_false',
        help='Dont archive images',
        dest='archive_images'
    )

def min_octree_depth(parser):
    parser.add_argument(
        '--min-octree-depth',
        action='store',
        default=8,
        type=int,
        help='Min depth for the octree.  Smaller octrees should be used for smaller point clouds.',
        metavar='MIN_OCTREE_DEPTH',
        dest='min_octree_depth',
    )

def max_octree_depth(parser):
    parser.add_argument(
        '--max-octree-depth',
        action='store',
        default=8,
        type=int,
        help='Max depth for the octree. Bigger octrees should be used for bigger point clouds.',
        metavar='MAX_OCTREE_DEPTH',
        dest='max_octree_depth',
    )

def solver_divide(parser):
    parser.add_argument(
        '--solver-divide',
        action='store',
        default=8,
        type=int,
        help='Invesely proportional to how much memory the poisson reconstruction will use, and directly proportional to how much time the algorithm will take.',
        metavar='SOLVER_DIVIDE',
        dest='solver_divide',
    )

def iso_divide(parser):
    parser.add_argument(
        '--iso-divide',
        action='store',
        default=8,
        type=int,
        help='Divide for your solver?',
        metavar='ISO_DIVIDE',
        dest='iso_divide'
    )

def point_cloud(parser):
    parser.add_argument(
        '--point-cloud',
        action='append',
        type=str,
        help='Point clouds to process.',
        metavar='POINT_CLOUD',
        dest='point_cloud',
    )

def sample_rate(parser):
    parser.add_argument(
        '--sample-rate',
        action='store',
        default=0.2,
        type=float,
        help='Samples used when culling points during fine alignment.',
        metavar='SAMPLE_RATE',
        dest='sample_rate',
    )

def max_samples(parser):
    parser.add_argument(
        '--max-samples',
        action='store',
        default=100000,
        type=int,
        help='Maximum number of samples to use when culling points during fine alignment.',
        metavar='MAX_SAMPLES',
        dest='max_samples',
    )

def min_samples(parser):
    parser.add_argument(
        '--min-samples',
        action='store',
        default=10000,
        type=int,
        help='Minimum number of samples to use',
        metavar='MIN_SAMPLES',
        dest='min_samples',
    )

def inlier_ratio(parser):
    parser.add_argument(
        '--inlier-ratio',
        action='store',
        default=0.9,
        type=float,
        help='Ratio of inliers.',
        metavar='INLIER_RATIO',
        dest='inlier_ratio',
    )

def max_iterations(parser):
    parser.add_argument(
        '--max-iterations',
        action='store',
        default=200,
        type=int,
        help='Maximum number of iterations to execute on fine alignment.',
        metavar='MAX_ITERATIONS',
        dest='max_iterations',
    )

def grid_size(parser):
    parser.add_argument(
        '--grid-size',
        action='store',
        default=0.5,
        type=float,
        help='Size of grid to project onto a pointcloud.  Within each cell of that grid a random point will be selected, and all other points will be removed.',
        metavar='GRID_SIZE',
        dest='grid_size',
    )

def scale(parser):
    parser.add_argument(
        '--scale',
        action='store',
        default=1.25,
        type=float,
        help='Scale value for mesh',
        metavar='SCALE',
        dest='scale',
    )

def plane_cut(parser):
    parser.add_argument(
        '--plane-cut',
        action='store_true',
        help='Cut model at the top',
        dest='plane_cut',
    )

def no_plane_cut(parser):
    parser.add_argument(
        '--no-plane-cut',
        action='store_true',
        help='Cut model at the top',
        dest='plane_cut',
    )

def manifold(parser):
    parser.add_argument(
        '--manifold',
        action='store_true',
        help='Make the model manifold',
        dest='manifold',
    )

def no_manifold(parser):
    parser.add_argument(
        '--no-manifold',
        action='store_false',
        help='Make the model manifold',
        dest='manifold',
    )

def calibration_images(parser):
    parser.add_argument(
        '--calib',
        '--calibration-images',
        action='append',
        type=str,
        help='Images to use during calibration',
        metavar='CALIBRATION_IMAGES',
        dest='calibration_images',
    )

def laser_calibration_images(parser):
    parser.add_argument(
        '--laser-calib',
        action='append',
        type=str,
        help='Images used to calibrate the laser',
        metavar='LASER_CALIBRATION_IMAGES',
        dest='laser_calibration_images',
    )

def background_image(parser):
    parser.add_argument(
        '--background-image',
        action='store',
        type=str,
        metavar='BACKGROUND_IMAGE',
        dest='background_image',
    )

def toggle_on(parser):
    parser.add_argument(
        '--toggle-on',
        action='store_true',
        help='Toggles power on',
        dest='toggle',
    )

def toggle_off(parser):
    parser.add_argument(
        '--toggle-off',
        action='store_false',
        help='Toggles power off',
        dest='toggle',
    )

def laser(parser):
    parser.add_argument(
        '--laser',
        action='store',
        type=str,
        default='both',
        help='Which laser to use',
        choices=('left', 'right', 'both', 'none'),
        metavar='LASER',
        dest='laser',
    )

def archive_point_clouds(parser):
    parser.add_argument(
        '--archive-point-clouds',
        action='store_true',
        dest='archive_point_clouds',
    )

def no_archive_point_clouds(parser):
    parser.add_argument(
        '--no-archive-point-clouds',
        action='store_true',
        dest='archive_point_clouds',
    )

def bounding_cylinder_top(parser):
    parser.add_argument(
        '--bounding-cylinder-top',
        type=float,
        default=100.0,
        action='store',
        metavar='BOUNDING_CYLINDER_TOP',
        dest='bounding_cylinder_top',
    )

def bounding_cylinder_bottom(parser):
    parser.add_argument(
        '--bounding-cylinder-bottom',
        type=float,
        default=100.0,
        action='store',
        metavar='BOUNDING_CYLINDER_BOTTOM',
        dest='bounding_cylinder_bottom',
    )

def bounding_cylinder_radius(parser):
    parser.add_argument(
        '--bounding-cylinder-radius',
        type=float,
        default=100.0,
        action='store',
        metavar='BOUNDING_CYLINDER_RADIUS',
        dest='bounding_cylinder_radius',
    )

def x_normal(parser):
    parser.add_argument(
        '--x-normal',
        type=float,
        default=0,
        metavar='X_NORMAL',
        dest='x_normal',
    )

def y_normal(parser):
    parser.add_argument(
        '--y-normal',
        type=float,
        default=0,
        metavar='Y_NORMAL',
        dest='y_normal',
    )

def z_normal(parser):
    parser.add_argument(
        '--z-normal',
        type=float,
        default=0,
        metavar='Z_NORMAL',
        dest='z_normal',
    )

def plane_origin(parser):
    parser.add_argument(
        '--plane-origin',
        type=float,
        default=200,
        metavar='PLANE_ORIGIN',
        dest='plane_origin',
    )

def smoothing_nearest_neighbors(parser):
    parser.add_argument(
        '--smoothing-nearest-neighbors',
        type=int,
        default=20,
        metavar='SMOOTHING_NEAREST_NEIGHBORS',
        dest='smoothing_nearest_neighbors',
    )

def smoothing_iterations(parser):
    parser.add_argument(
        '--smoothing-iterations',
        type=int,
        default=0,
        metavar='SMOOTHING_ITERATIONS',
        dest='smoothing_iterations',
    )

def mesh_id(parser):
    parser.add_argument(
        '--mesh-id',
        type=int,
        metavar='MESH_ID',
        dest='mesh_id',
    )

def point_cloud_id(parser):
    parser.add_argument(
        '--point-cloud-id',
        type=int,
        metavar='POINT_CLOUD_ID',
        dest='point_cloud_id',
    )

def archive_path(parser):
    parser.add_argument(
        '--archive-path',
        type=str,
        default=None,
        metavar='ARCHIVE_PATH',
        dest='archive_path'
    )

def side(parser):
    parser.add_argument(
        '--side',
        type=str,
        default=None,
        choices=('left', 'right', 'both', 'none'),
        metavar='SIDE',
        dest='side'
    )

def vid(parser):
    parser.add_argument(
        '--vid',
        type=int,
        metavar='VID',
        dest='vid'
    )

def pid(parser):
    parser.add_argument(
        '--pid',
        type=int,
        metavar='PID',
        dest='pid'
    )

def iserial(parser):
    parser.add_argument(
        '--iserial',
        type=int,
        metavar='ISERIAL',
        dest='iserial'
    )

def input_files(parser):
    parser.add_argument(
        '--input-file',
        action='append',
        type=str,
        help='Point clouds used for global alignment',
        metavar='GLOBAL_ALIGN_INPUT_FILES',
        dest='input_files',
    )

def input_path(parser):
    parser.add_argument(
        '--input-path',
        type=str,
        default=None,
        metavar='INPUT_PATH',
        dest='input_path'
    )

def src_id(parser):
    parser.add_argument(
        '--src-id',
        type=int,
        metavar='SRC_ID',
        dest='src_id',
    )

def dst_id(parser):
    parser.add_argument(
        '--dst-id',
        type=int,
        metavar='DST_ID',
        dest='dst_id',
    )

def src_side(parser):
    parser.add_argument(
        '--src-side',
        type=str,
        default=None,
        choices=('left', 'right', 'both', 'none'),
        metavar='SRC_SIDE',
        dest='src_side'
    )

def dst_side(parser):
    parser.add_argument(
        '--dst-side',
        type=str,
        default=None,
        choices=('left', 'right', 'both', 'none'),
        metavar='DST_SIDE',
        dest='dst_side'
    )

def remove_outliers(parser):
    parser.add_argument(
        '--remove-outliers',
        action='store_true',
        help='Remove outliers when processing point clouds',
        dest='remove_outliers'
    )

def dont_remove_outliers(parser):
    parser.add_argument(
        '--dont-remove-outliers',
        action='store_false',
        help='Do not remove outliers when processing point clouds',
        dest='remove_outliers'
    )

def wifi_path(parser):
    parser.add_argument(
        '--wifi-path',
        type=str,
        dest='wifi_path'
    )

def wifi_password(parser):
    parser.add_argument(
        '--wifi-password',
        type=str,
        default=None,
        dest='wifi_password'
    )
