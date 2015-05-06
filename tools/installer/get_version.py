import sys, os
path_to_trunk = os.path.join('3dprinteros-client/client')
sys.path.append(path_to_trunk)
import version
version
with open('version.txt', 'w') as f:
    f.write(version.version)