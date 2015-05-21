from __future__ import absolute_import

from .AnchorProcessor import AnchorProcessor
import makerbot_driver

class RepSinglePrimeProcessor(AnchorProcessor):

    def __init__(self):
        super(RepSinglePrimeProcessor, self).__init__()
        self.looking_for_first_move = True
        self.do_anchor = True

    def _transform_anchor(self, match):
        if "(Anchor Start)" in  match.string:
            self.do_anchor = False
        if self.looking_for_first_move:
            if getattr(self, 'profile', None):
                start_x = self.profile.values['print_start_sequence']['start_position']['start_x']
                start_y = self.profile.values['print_start_sequence']['start_position']['start_y']
            else:
                start_x = -112
                start_y = -73
            codes, flags, comments = makerbot_driver.Gcode.parse_line(match.string)
            prime_codes = [
                    "G1 X105.400 Y-74.000 Z0.270 F9000.000 (Extruder Prime Dry Move)\n",
                    "G1 X%i Y%i Z0.270 F1800.000 E25.000 (Extruder Prime Start)\n" % (start_x, start_y),
                    "G92 A0 B0 (Reset after prime)\n",
            ]
            if self.do_anchor:
                prime_codes.extend(super(RepSinglePrimeProcessor, self)._transform_anchor(match))
            self.looking_for_first_move = False
            return prime_codes
        else:
            return match.string
