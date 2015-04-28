import sys
import os
import re

# Delete E* extrusion commands from G1 gcodes
# For purposes when there is not enough to delete or reduce heating gcodes (ZMorph)
def airprint():
    args = sys.argv
    if len(args) != 3:
        print 'Please launch script as "python make_airprint.py INPUT_FILE OUTPUT_FILE"'
        return
    if not os.path.isfile(args[1]):
        print 'Input file not found'
        return
    try:
        with open(args[1], 'r') as f:
            with open(args[2], 'w') as n:
                for line in f:
                    if line.startswith('G1'):
                        line = re.sub('( E[\d\.]+)$', '', line)
                    n.write(line)
    except Exception as e:
        print 'Error occured:\n%s' % str(e)
    else:
        print 'File is created at:\n%s' % os.path.abspath(n.name)

if __name__ == '__main__':
    airprint()