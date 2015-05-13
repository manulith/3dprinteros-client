import sys
import os
path_to_client = os.path.join('3dprinteros-client', 'client')
sys.path.append(path_to_client)
import version
with open('version.txt', 'w') as f:
	f.write(version.version)