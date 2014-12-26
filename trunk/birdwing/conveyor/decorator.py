# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/decorator.py
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

import inspect
import conveyor.log

def args(*funcs):
    def decorator(cls):
        # NOTE: decorators are applied bottom-up. To support positional
        # arguments (listed in the source file in a sensible manner) we have to
        # prepend the new argument functions to the list instead of appending
        # them.
        args_funcs = list(funcs) + getattr(cls, '_args_funcs', [])
        setattr(cls, '_args_funcs', args_funcs)
        return cls
    return decorator


def command(command_class):
    def decorator(cls):
        command_classes = [command_class] + getattr(cls, '_command_classes', [])
        setattr(cls, '_command_classes', command_classes)
        return cls
    return decorator


def jsonrpc(cxx_types=None):
    '''Mark a function as a JSON-RPC method

    This decorator is also used to set a C++ type for each
    argument. The cxx_types argument must be a dict containing a key
    for each argument of the JSON-RPC function (except for 'self'),
    with a C++ type as its value.

    The C++ types are used to generate code for conveyor-cpp. No
    validation is performed on the C++ type, but an exception will be
    raised if an argument name is not in cxx_types.'''
    def validate_type_annotations(func, cxx_types=None):
        ''' Check each argument after self for a matching type annotation'''
        cxx_types = {} if not cxx_types else cxx_types
        arg_names = inspect.getargspec(func).args[1:]
        log = conveyor.log.getlogger(func)
        
        if arg_names and not cxx_types:
            # No type annotation, C++ code gen won't happen for this function
            return

        # Check that each arg has a corresponding C++ type
        for a in arg_names:
            if a not in cxx_types:
                raise Exception(
                    '{func}: missing type annotation for "{arg}"'.format(
                        arg=a, func=func.func_name))
        # Check that there are no extraneous cxx_type fields
        for t in cxx_types:
            if t not in arg_names:
                raise Exception(
                    '{func}: extraneous type annotation for "{arg}"'.format(
                        arg=t, func=func.func_name))

    def decorator(func):
        validate_type_annotations(func, cxx_types)
        setattr(func, '_jsonrpc', True)
        return func
    return decorator

def run_job(timeout=30.0, heartbeat_timeout=None):
    def outter_decorator(func):
        def decorator(*args, **kwargs):
            job = func(*args, **kwargs)
            return conveyor.util.execute_job(job, timeout, heartbeat_timeout)
        return decorator
    return outter_decorator

def check_firmware_version(func):
    """
    Decorator to check if the firmware is up to date. We can't reject machines 
    that have out of date firmware, since we need to be able to update them.
    Instead we just leverage this decorator on functions that we want to block.
    """
    def decorator(self, *args, **kwargs):
        if not self._is_compatible_firmware(self._firmware_version):
            self._log.info("Conveyor is not compatible with Firmware "
                                 "version {0}, but we're going to try and "
                                 "play nice".format(self._firmware_version))
        # Pass the implicit self arg
        func(self, *args, **kwargs)
    return decorator
