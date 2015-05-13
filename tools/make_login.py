import sys
import os

path = os.path.dirname(__file__)
path = os.path.abspath(os.path.join(path, '..', 'trunk'))
sys.path.append(path)
import paths
import user_login

args = sys.argv
if len(args) != 3:
    print 'Please launch script as "python make_login.py LOGIN PASSWORD"'
else:
    if user_login.write_login(args[1], args[2]):
        print 'File successfully created in :'
        print str(paths.get_paths_to_settings_folder()[0])
    else:
        print 'Error, file was not created'
