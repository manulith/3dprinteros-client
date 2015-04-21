#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys


path_to_trunk = os.path.join("..", 'trunk')
sys.path.append(path_to_trunk)
try:
	import version
except IOError as e:
	print e
else:
    print version.version
    print version.build
    print version.commit