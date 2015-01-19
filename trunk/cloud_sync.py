import utils
utils.init_path_to_libs() #TODO: for standalone run. Remove when integrated into Client
import sys
import os
import ctypes
import time
import threading
import traceback

import requests

from os.path import join
from subprocess import Popen, PIPE

if sys.platform.startswith('linux'):
    HOME_PATH = os.environ.get('HOME')
else:
    HOME_PATH = os.environ.get('HOMEPATH')

PATH = join(HOME_PATH, 'Cloudsync')
TEMP_PATH = join(PATH, '.temp')
BIG_FILES_PATH = join(TEMP_PATH, 'big')
NORMAL_FILES_PATH = join(TEMP_PATH, 'normal')
SENDED_PATH = join(PATH, 'Sended')
UNSENDABLE_PATH = join(PATH, 'Unsendable')
BIG_FILE_SIZE = 10 * 1024 * 1024  #Files over ~10Mb are big

problem_files = {}
run_status = {'working': False}
big_files_thread = None
normal_files_thread = None
thread_waiting_timeout = 2


class SendFiles(threading.Thread):
    #For paralel big and small file sending
    def __init__(self, file_path, problem_files):
        self.problem_files = problem_files
        threading.Thread.__init__(self)
        self.file_path = file_path
        self.run_flag = True
        self.intialized = True

    def send(self):
        files_to_send = check_files(get_list(self.file_path), self.file_path)
        for file_to_send in files_to_send:
            if send_file(join(self.file_path, file_to_send)):
                after_send(join(self.file_path, file_to_send))
            else:
                self.problem_files[join(self.file_path, file_to_send)] = \
                    self.problem_files.pop(join(self.file_path, file_to_send), 0) + 1

    def run(self):
        while self.run_flag == True:
            try:
                self.send()
            except Exception, e:
                traceback.print_exc()
                break

    def stop(self):
        self.run_flag = False


def get_os():
    if sys.platform.startswith('win'):
        return "win"
    elif sys.platform.startswith('linux'):
        return "nix"
    elif sys.platform.startswith('darwin'):
        return "mac"
    else:
        raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')

def create_folders(path):
    """
    Create directory tree if not extst
    :param path:  Path to dropfolder dir root
    """

    paths = [path, TEMP_PATH, BIG_FILES_PATH, NORMAL_FILES_PATH, SENDED_PATH, UNSENDABLE_PATH]
    for one_path in paths:
        if os.path.exists(one_path) == False:
            os.mkdir(one_path)

    if get_os() == "win":
        ctypes.windll.kernel32.SetFileAttributesW(TEMP_PATH, 2)
        create_shortcuts_win()

def move_file_safe(old_filename, new_filename):
    #os.rename(join(PATH,file_to_send),
    # join(NORMAL_FILES_PATH,hashlib.md5(str(time.time()).encode('utf-8')).hexdigest()+file_to_send))
    name_count = 1
    filename, file_ext = os.path.splitext(new_filename)
    while os.path.exists(new_filename):
        new_filename = filename + " (" + str(name_count) + ")" + file_ext
        name_count += 1
    os.rename(old_filename, new_filename)

def create_shortcuts_win():
    """
    Add icons and links
    :param path: Path to dropfolder dir root
    """
    import winshell
    favourites_path = join(HOME_PATH, "links\Cloudsync.lnk")
    sendto_path = join(HOME_PATH, "AppData\Roaming\Microsoft\Windows\SendTo\Cloudsync.lnk")
    desktop_path = join(HOME_PATH, "desktop\CloudSync Folder.lnk")

    winshell.CreateShortcut(
        Path = favourites_path,
        Target = PATH
        )
    winshell.CreateShortcut(
        Path = sendto_path,
        Target = PATH
        )
    winshell.CreateShortcut(
        Path = desktop_path,
        Target = PATH
        )

    #virtual drive creating
    process = Popen(['subst'], stdout = PIPE, stderr = PIPE)
    stdout, stderr = process.communicate()
    if stdout == '':
        print 'Creating virtual drive...'
        abspath = os.path.abspath(PATH)
        letters = 'HIJKLMNOPQRSTUVWXYZ'
        for letter in letters:
            process = Popen(['subst', letter + ':', abspath], stdout = PIPE, stderr = PIPE)
            stdout, stderr = process.communicate()
            if stdout == '':
                print 'Created! ' + letter + ':'
                break

def remove_shortcuts_win():
    favourites_path = join(HOME_PATH, "links\Cloudsync.lnk")
    sendto_path = join(HOME_PATH, "AppData\Roaming\Microsoft\Windows\SendTo\Cloudsync.lnk")
    desktop_path = join(HOME_PATH, "desktop\CloudSync Folder.lnk")
    try:
        process = Popen(['subst'], stdout = PIPE, stderr = PIPE)
        stdout, stderr = process.communicate()
        if stdout != '':
            stdout = stdout[0]
            process = Popen(['subst', stdout + ':', '/d'], stdout = PIPE, stderr = PIPE)
            stdout, stderr = process.communicate()
            if stdout == '':
                print "Virtual drive removed."
            else:
                print stdout
        os.remove(sendto_path)
        os.remove(favourites_path)
        os.remove(desktop_path)
        print "Windows shortcuts removed!"
    except:
        pass

def get_list(path):
    """
    Get List files from dir
    :param path: subj
    :return: List files
    """
    file_list = os.listdir(path)
    return [i for i in file_list if (os.path.isfile(path + os.sep + i) and i != "Desktop.ini")]

def check_files(files_to_check, filepath = PATH):
    """
    Check for files fully loaded to dropfolder dir (constant size and date in 1s)
    :param files_to_check: List files to check (without path)
    :param filepath: path to files who will be checked
    :return: List files ready to next step
    """
    old_files = {}
    to_send = []
    for _ in range(2):
        if not old_files:
            for some_file in files_to_check:
                old_files[some_file] = {"Size": os.path.getsize(join(filepath, some_file)), "Date": os.path.getatime(join(filepath, some_file))}
        else:
            #print (files_to_check)
            print(old_files)
            for some_file in files_to_check:
                if (old_files[some_file]["Size"] == os.path.getsize(join(filepath, some_file))) and \
                        (old_files[some_file]["Date"] == os.path.getatime(join(filepath, some_file))):
                    try:
                        f = open(join(filepath, some_file), 'a')
                    except Exception:
                        print(some_file + " - is not writeable file! m.b. opened in another programm")
                    else:
                        to_send.append(some_file)
                        f.close()
                        #print (join(path,some_file)+".checked()")
        time.sleep(1)
    return to_send
    #if file no change in 2s
    #if file writeable
    #add to_send list

def prepare_to_send(files_to_send):
    """
    Prepare - move away from sync dir, separate by size
    :param files_to_send: list filenames (without path)
    """
    for file_to_send in files_to_send:
        if os.path.getsize(join(PATH, file_to_send)) < BIG_FILE_SIZE:
            move_file_safe(join(PATH, file_to_send), join(NORMAL_FILES_PATH, file_to_send))
        else:
            move_file_safe(join(PATH, file_to_send), join(BIG_FILES_PATH, file_to_send))
            #in this place in future i make may be compression or something else

def send_file(file_path):
    #send file
    url = 'https://acorn.3dprinteros.com/autoupload/'
    token = {"printer_token": utils.read_token()}
    f = {"file": open(file_path)}
    r = requests.post(url, data=token, files=f)
    s = str(r.text)
    print 'Cloudsync response: ' + s
    if '"result":true' in s:
        return (True)

def after_send(file_path):
    print("After successfull sending I move files to sended:" + file_path)
    move_file_safe(file_path, join(SENDED_PATH, os.path.basename(file_path)))
    #delete file
    #set status

def check_problem_files(problem_files):
    """If more than 11 times did not sended move to 'unsended' dir"""
    for some_file in problem_files:
        if problem_files[some_file] > 10:
            print("Problem in:" + file + ":" + str(problem_files[some_file]))
            os.rename(some_file, join(UNSENDABLE_PATH, os.path.basename(some_file)))
            problem_files[some_file] = -1

def launch():
    create_folders(PATH)
    run_status['working'] = True
    big_files_thread = SendFiles(BIG_FILES_PATH, problem_files).start()
    normal_files_thread = SendFiles(NORMAL_FILES_PATH, problem_files).start()
    main_loop()
    run_status['working'] = False

#TODO: fix stopping cloud_sync
def stop():
    big_files_thread.stop().join(thread_waiting_timeout)
    normal_files_thread.stop().join(thread_waiting_timeout)
    run_status['working'] = False


def main_loop():
    while run_status['working']:
        checked_files = check_files(get_list(PATH), PATH)
        prepare_to_send(checked_files)
        check_problem_files(problem_files)


if __name__ == "__main__":
    launch()