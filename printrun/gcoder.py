#!/usr/bin/env python
# This file is copied from GCoder.
#
# GCoder is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# GCoder is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Printrun.  If not, see <http://www.gnu.org/licenses/>.

import sys
import re
import math
import datetime
import logging
from array import array

gcode_parsed_args = ["x", "y", "e", "f", "z", "i", "j"]
gcode_parsed_nonargs = ["g", "t", "m", "n"]
to_parse = "".join(gcode_parsed_args + gcode_parsed_nonargs)
gcode_exp = re.compile("\([^\(\)]*\)|;.*|[/\*].*\n|([%s])([-+]?[0-9]*\.?[0-9]*)" % to_parse)
gcode_strip_comment_exp = re.compile("\([^\(\)]*\)|;.*|[/\*].*\n")
m114_exp = re.compile("\([^\(\)]*\)|[/\*].*\n|([XYZ]):?([-+]?[0-9]*\.?[0-9]*)")
specific_exp = "(?:\([^\(\)]*\))|(?:;.*)|(?:[/\*].*\n)|(%s[-+]?[0-9]*\.?[0-9]*)"
move_gcodes = ["G0", "G1", "G2", "G3"]

class PyLine(object):

    __slots__ = ('x', 'y', 'z', 'e', 'f', 'i', 'j',
                 'raw', 'command', 'is_move',
                 'relative', 'relative_e',
                 'current_x', 'current_y', 'current_z', 'extruding',
                 'current_tool',
                 'gcview_end_vertex')

    def __init__(self, l):
        self.raw = l

    def __getattr__(self, name):
        return None

class PyLightLine(object):

    __slots__ = ('raw', 'command')

    def __init__(self, l):
        self.raw = l

    def __getattr__(self, name):
        return None

try:
    import gcoder_line
    Line = gcoder_line.GLine
    LightLine = gcoder_line.GLightLine
except Exception, e:
    logging.warning("Memory-efficient GCoder implementation unavailable: %s" % e)
    Line = PyLine
    LightLine = PyLightLine
else:
    logging.warning("Memory-efficient GCoder is enabled!")

def find_specific_code(line, code):
    exp = specific_exp % code
    bits = [bit for bit in re.findall(exp, line.raw) if bit]
    if not bits: return None
    else: return float(bits[0][1:])

def S(line):
    return find_specific_code(line, "S")

def P(line):
    return find_specific_code(line, "P")

def split(line):
    split_raw = gcode_exp.findall(line.raw.lower())
    if split_raw and split_raw[0][0] == "n":
        del split_raw[0]
    if not split_raw:
        line.command = line.raw
        line.is_move = False
        logging.warning("raw G-Code line \"%s\" could not be parsed" % line.raw)
        return [line.raw]
    command = split_raw[0]
    line.command = command[0].upper() + command[1]
    line.is_move = line.command in move_gcodes
    return split_raw

def parse_coordinates(line, split_raw, imperial = False, force = False):
    # Not a G-line, we don't want to parse its arguments
    if not force and line.command[0] != "G":
        return
    unit_factor = 25.4 if imperial else 1
    for bit in split_raw:
        code = bit[0]
        if code not in gcode_parsed_nonargs and bit[1]:
            setattr(line, code, unit_factor * float(bit[1]))

class Layer(list):

    __slots__ = ("duration", "z")

    def __init__(self, lines, z = None):
        super(Layer, self).__init__(lines)
        self.z = z

class GCode(object):

    line_class = Line

    lines = None
    layers = None
    all_layers = None
    layer_idxs = None
    line_idxs = None
    append_layer = None
    append_layer_id = None

    imperial = False
    relative = False
    relative_e = False
    current_tool = 0
    # Home position: current absolute position counted from machine origin
    home_x = 0
    home_y = 0
    home_z = 0
    # Current position: current absolute position counted from machine origin
    current_x = 0
    current_y = 0
    current_z = 0
    # For E this is the absolute position from machine start
    current_e = 0
    total_e = 0
    max_e = 0
    # Current feedrate
    current_f = 0
    # Offset: current offset between the machine origin and the machine current
    # absolute coordinate system (as shifted by G92s)
    offset_x = 0
    offset_y = 0
    offset_z = 0
    offset_e = 0
    # Expected behavior:
    # - G28 X => X axis is homed, offset_x <- 0, current_x <- home_x
    # - G92 Xk => X axis does not move, so current_x does not change
    #             and offset_x <- current_x - k,
    # - absolute G1 Xk => X axis moves, current_x <- offset_x + k
    # How to get...
    # current abs X from machine origin: current_x
    # current abs X in machine current coordinate system: current_x - offset_x

    filament_length = None
    duration = None
    xmin = None
    xmax = None
    ymin = None
    ymax = None
    zmin = None
    zmax = None
    width = None
    depth = None
    height = None

    est_layer_height = None

    # abs_x is the current absolute X in machine current coordinate system
    # (after the various G92 transformations) and can be used to store the
    # absolute position of the head at a given time
    def _get_abs_x(self):
        return self.current_x - self.offset_x
    abs_x = property(_get_abs_x)

    def _get_abs_y(self):
        return self.current_y - self.offset_y
    abs_y = property(_get_abs_y)

    def _get_abs_z(self):
        return self.current_z - self.offset_z
    abs_z = property(_get_abs_z)

    def _get_abs_e(self):
        return self.current_e - self.offset_e
    abs_e = property(_get_abs_e)

    def _get_abs_pos(self):
        return (self.abs_x, self.abs_y, self.abs_z)
    abs_pos = property(_get_abs_pos)

    def _get_current_pos(self):
        return (self.current_x, self.current_y, self.current_z)
    current_pos = property(_get_current_pos)

    def _get_home_pos(self):
        return (self.home_x, self.home_y, self.home_z)

    def _set_home_pos(self, home_pos):
        if home_pos:
            self.home_x, self.home_y, self.home_z = home_pos
    home_pos = property(_get_home_pos, _set_home_pos)

    def _get_layers_count(self):
        return len(self.all_zs)
    layers_count = property(_get_layers_count)

    def __init__(self, data = None, home_pos = None,
                 layer_callback = None, deferred = False):
        if not deferred:
            self.prepare(data, home_pos, layer_callback)

    def prepare(self, data = None, home_pos = None, layer_callback = None):
        self.home_pos = home_pos
        if data:
            line_class = self.line_class
            self.lines = [line_class(l2) for l2 in
                          (l.strip() for l in data)
                          if l2]
            self._preprocess(build_layers = True,
                             layer_callback = layer_callback)
        else:
            self.lines = []
            self.append_layer_id = 0
            self.append_layer = Layer([])
            self.all_layers = [self.append_layer]
            self.all_zs = set()
            self.layers = {}
            self.layer_idxs = array('I', [])
            self.line_idxs = array('I', [])

    def __len__(self):
        return len(self.line_idxs)

    def __iter__(self):
        return self.lines.__iter__()

    def prepend_to_layer(self, commands, layer_idx):
        # Prepend commands in reverse order
        commands = [c.strip() for c in commands[::-1] if c.strip()]
        layer = self.all_layers[layer_idx]
        # Find start index to append lines
        # and end index to append new indices
        start_index = self.layer_idxs.index(layer_idx)
        for i in range(start_index, len(self.layer_idxs)):
            if self.layer_idxs[i] != layer_idx:
                end_index = i
                break
        else:
            end_index = i + 1
        end_line = self.line_idxs[end_index - 1]
        for i, command in enumerate(commands):
            gline = Line(command)
            # Split to get command
            split(gline)
            # Force is_move to False
            gline.is_move = False
            # Insert gline at beginning of layer
            layer.insert(0, gline)
            # Insert gline at beginning of list
            self.lines.insert(start_index, gline)
            # Update indices arrays & global gcodes list
            self.layer_idxs.insert(end_index + i, layer_idx)
            self.line_idxs.insert(end_index + i, end_line + i + 1)
        return commands[::-1]

    def rewrite_layer(self, commands, layer_idx):
        # Prepend commands in reverse order
        commands = [c.strip() for c in commands[::-1] if c.strip()]
        layer = self.all_layers[layer_idx]
        # Find start index to append lines
        # and end index to append new indices
        start_index = self.layer_idxs.index(layer_idx)
        for i in range(start_index, len(self.layer_idxs)):
            if self.layer_idxs[i] != layer_idx:
                end_index = i
                break
        else:
            end_index = i + 1
        self.layer_idxs = self.layer_idxs[:start_index] + array('I', len(commands) * [layer_idx]) + self.layer_idxs[end_index:]
        self.line_idxs = self.line_idxs[:start_index] + array('I', range(len(commands))) + self.line_idxs[end_index:]
        del self.lines[start_index:end_index]
        del layer[:]
        for i, command in enumerate(commands):
            gline = Line(command)
            # Split to get command
            split(gline)
            # Force is_move to False
            gline.is_move = False
            # Insert gline at beginning of layer
            layer.insert(0, gline)
            # Insert gline at beginning of list
            self.lines.insert(start_index, gline)
        return commands[::-1]

    def append(self, command, store = True):
        command = command.strip()
        if not command:
            return
        gline = Line(command)
        self._preprocess([gline])
        if store:
            self.lines.append(gline)
            self.append_layer.append(gline)
            self.layer_idxs.append(self.append_layer_id)
            self.line_idxs.append(len(self.append_layer))
        return gline

    def _preprocess(self, lines = None, build_layers = False,
                    layer_callback = None):
        """Checks for imperial/relativeness settings and tool changes"""
        if not lines:
            lines = self.lines
        current_z = self.current_z


        # Store this one out of the build_layers scope for efficiency
        cur_layer_has_extrusion = False

        # Initialize layers and other global computations
        if build_layers:
            lastz = 0.0

            all_layers = self.all_layers = []
            all_zs = self.all_zs = set()
            layer_idxs = self.layer_idxs = []
            line_idxs = self.line_idxs = []

            layer_id = 0
            layer_line = 0

            last_layer_z = None
            prev_z = None
            prev_base_z = (None, None)
            cur_z = None
            cur_lines = []

        if self.line_class != Line:
            get_line = lambda l: Line(l.raw)
        else:
            get_line = lambda l: l
        for true_line in lines:
            line = get_line(true_line)
            if line.command:
                if build_layers:
                    if line.command == "G0" or line.command == "G1":
                        z = line.z if line.z is not None else lastz
                        lastz = z

                    # FIXME : looks like this needs to be tested with "lift Z on move"
                    if line.z is not None:
                        if line.command == "G92":
                            cur_z = line.z
                        elif line.is_move:
                            if line.relative and cur_z is not None:
                                cur_z += line.z
                            else:
                                cur_z = line.z

                    # FIXME: the logic behind this code seems to work, but it might be
                    # broken
                    if cur_z != prev_z:
                        if prev_z is not None and last_layer_z is not None:
                            offset = self.est_layer_height if self.est_layer_height else 0.01
                            if abs(prev_z - last_layer_z) < offset:
                                if self.est_layer_height is None:
                                    zs = sorted([l.z for l in all_layers if l.z is not None])
                                    heights = [round(zs[i + 1] - zs[i], 3) for i in range(len(zs) - 1)]
                                    heights = [height for height in heights if height]
                                    if len(heights) >= 2: self.est_layer_height = heights[1]
                                    elif heights: self.est_layer_height = heights[0]
                                    else: self.est_layer_height = 0.1
                                base_z = round(prev_z - (prev_z % self.est_layer_height), 2)
                            else:
                                base_z = round(prev_z, 2)
                        else:
                            base_z = prev_z

                        if base_z != prev_base_z:
                            new_layer = Layer(cur_lines, base_z)
                            all_layers.append(new_layer)
                            if cur_layer_has_extrusion and prev_z not in all_zs:
                                all_zs.add(prev_z)
                            cur_lines = []
                            cur_layer_has_extrusion = False
                            layer_id += 1
                            layer_line = 0
                            last_layer_z = base_z
                            if layer_callback is not None:
                                layer_callback(self, len(all_layers) - 1)

                        prev_base_z = base_z

            if build_layers:
                cur_lines.append(true_line)
                layer_idxs.append(layer_id)
                line_idxs.append(layer_line)
                layer_line += 1
                prev_z = cur_z

        self.current_z = current_z

        if build_layers:
            if cur_lines:
                new_layer = Layer(cur_lines, prev_z)
                new_layer.duration = 0
                all_layers.append(new_layer)
                if cur_layer_has_extrusion and prev_z not in all_zs:
                    all_zs.add(prev_z)

            self.append_layer_id = len(all_layers)
            self.append_layer = Layer([])
            self.append_layer.duration = 0
            all_layers.append(self.append_layer)
            self.layer_idxs = array('I', layer_idxs)
            self.line_idxs = array('I', line_idxs)

    def idxs(self, i):
        return self.layer_idxs[i], self.line_idxs[i]

    def estimate_duration(self):
        return self.layers_count, self.duration

class LightGCode(GCode):
    line_class = LightLine

def main():
    if len(sys.argv) < 2:
        print "usage: %s filename.gcode" % sys.argv[0]
        return

    print "Line object size:", sys.getsizeof(Line("G0 X0"))
    print "Light line object size:", sys.getsizeof(LightLine("G0 X0"))
    gcode = GCode(open(sys.argv[1], "rU"))

    print "Dimensions:"
    xdims = (gcode.xmin, gcode.xmax, gcode.width)
    print "\tX: %0.02f - %0.02f (%0.02f)" % xdims
    ydims = (gcode.ymin, gcode.ymax, gcode.depth)
    print "\tY: %0.02f - %0.02f (%0.02f)" % ydims
    zdims = (gcode.zmin, gcode.zmax, gcode.height)
    print "\tZ: %0.02f - %0.02f (%0.02f)" % zdims
    print "Filament used: %0.02fmm" % gcode.filament_length
    print "Number of layers: %d" % gcode.layers_count
    print "Estimated duration: %s" % gcode.estimate_duration()[1]

if __name__ == '__main__':
    main()
