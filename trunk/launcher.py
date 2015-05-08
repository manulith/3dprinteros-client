import os
import sys
import time
import tempfile
import traceback
import webbrowser

import app
import config

pid_file_name = "3dprinteros.pid"
tmp_path = tempfile.gettempdir()
pid_file_path = os.path.join(tmp_path, pid_file_name)

def get_process_list():
    print "Getting process list"
    if sys.platform.startswith('win'):
        tasks = os.popen('tasklist /svc').readlines()
        task_pids = []
        for task in tasks:
            words = task.split()
            if len(words) > 1:
                task_pids.append(words[1])
        #task_pids = map(lambda x: x.split()[1], filter(lambda x: len(x.split()) > 1, tasks))
    elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
        tasks = os.popen('ps ax').readlines()
        task_pids = map(lambda x: x.split()[0], tasks)
    else: raise RuntimeError("Your OS is not supported by 3DPrinterOS")
    return task_pids

def run():
    print "Launching 3DPrinterOS"
    with open(pid_file_path, "w") as f:
        f.write(str(os.getpid()))
    while app.reboot_flag:
        try:
            tdprinteros = app.App()
            del(tdprinteros)
        except SystemExit:
            pass
        except:
            trace = traceback.format_exc()
            print trace
            with open(config.config['error_file'], "a") as f:
                f.write(time.ctime() + "\n" + trace + "\n")

try:
    f = open(pid_file_path)
except IOError:
    run()
else:
    pid_in_file = f.read()
    f.close()
    if pid_in_file in get_process_list():
        print "3DPrinterOS is already running - opening browser window"
        webbrowser.open("http://127.0.0.1:8008", 2, True)
    else:
        run()



