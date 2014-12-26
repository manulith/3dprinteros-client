"""
A RepDualstrusionPrimeProcessor (what a mouthful).

This processor is designed to look through a gcode file and make sure
both nozzles and primed for printing.  This is done by looking for the first
move, then having two extrusion commands for both nozzles.
"""

from __future__ import absolute_import

import re
import makerbot_driver

from .LineTransformProcessor import LineTransformProcessor

class RepDualstrusionPrimeProcessor(LineTransformProcessor):

    def __init__(self):
        super(RepDualstrusionPrimeProcessor, self).__init__()
        map_addendum = {
            re.compile('M135\s[tT]\d'): self._set_toolhead,
            re.compile('G1'): self._add_prime,
        }
        self.code_map.update(map_addendum)
        self.looking_for_first_move = True
        self.current_toolchange = None

    def _set_toolhead(self, match):
        self.current_toolchange = match.string
        return self.current_toolchange

    @staticmethod
    def _get_inactive_toolhead(toolchange):
        (codes, flags, comments) = makerbot_driver.Gcode.parse_line(toolchange)
        active_toolhead = codes['T']
        inactive_code_map = {0: 'B', 1: 'A'}
        return inactive_code_map[active_toolhead]

    def _get_retract_commands(self, profile, toolchange):
        inactive_toolhead = self._get_inactive_toolhead(toolchange)
        retract_commands = [
            "M135 T%i\n" % (0 if inactive_toolhead == 'A' else 1),
            "G1 %s-%i F%i\n" % (inactive_toolhead, profile.values['dualstrusion']['retract_distance_mm'], profile.values['dualstrusion']['snort_feedrate']),
            "G92 %s0\n" % (inactive_toolhead),
        ]
        return retract_commands

    def _add_prime(self, match):
        toadd = []
        # If there is no current toolchange, we make contrive our own based
        # on the G1 command we just got.  If that command has no toolhead,
        # we default to the A axis.
        if self.looking_for_first_move:
            if getattr(self, 'profile', None):
                start_x = self.profile.values['print_start_sequence']['start_position']['start_x']
                start_y = self.profile.values['print_start_sequence']['start_position']['start_y']
            else:
                start_x = -112
                start_y = -73
            end_x = 105.4
            offset_start_y = start_y - 1
            toadd.extend([
                "M135 T0\n",
                "G1 X%i Y%i Z0.270 F1800.000 (Move to Start Position)\n" % (start_x, start_y),
                "G1 X%i Y%i Z0.270 F1800.000 A25.000 (Right Prime)\n" % (end_x, start_y),
                "M135 T1\n",
                "G1 X%i Y%i Z0.270 F9000 (Left Prime Move to Offset position)\n" % (end_x, offset_start_y),
                "G1 X%i Y%i Z0.270 F1800.000 B25.000 (Left Prime)\n" % (start_x, offset_start_y),
                "G92 A0 B0 (Reset after prime)\n",
            ])
            # If there is no current_toolchange, we're probably processing a 
            # MG print, so we just continue and dont try to add it (since MG
            # takes care of this for us
            if self.current_toolchange:
                if(self.profile.values['dualstrusion']['retract_distance_mm'] > 0):
                    #If there is no retract there is no need to get the retract commands
                    toadd.extend(self._get_retract_commands(self.profile, self.current_toolchange))
                toadd.append(self.current_toolchange)
        self.looking_for_first_move = False
        return toadd + [match.string]
