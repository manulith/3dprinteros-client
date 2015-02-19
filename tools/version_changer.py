import re
import sys
import os.path


def replace_build_and_commit(text):	
	lines = []
	for line in text.split("\n"):
		if line and not 'commit' in line and not 'build' in line and line != "\n" and line != " ":
			lines.append(line + "\n")
	lines.append('build = "' + str(build_number) + '"\n')
	if commit_name:				
		lines.append('commit = "' + str(commit_name) + '"\n')	
	text = "".join(lines)
	print "OUTPUT=\n" + text 
	return text

def modify_file(file_name):
	with open(file_name, "r+") as f:
			old = f.read()
			f.seek(0)
			f.write(replace_build_and_commit(old))

build_number = sys.argv[1]
commit_name = None
if len(sys.argv) > 1:
	commit_name = sys.argv[2]
version_file_name = 'version.py'
path_to_version_file = os.path.join("..", 'trunk', version_file_name)
try:
	modify_file(path_to_version_file)
except IOError as e:
	print e
	try:
		modify_file(version_file_name)
	except IOError as e:
		print e
	else:
		print "Success"
else:
	print "Success"



