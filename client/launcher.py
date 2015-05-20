#!/usr/bin/env python

#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

# Author: Vladimir Avdeev <another.vic@yandex.ru> 2015

import os
import sys
import tempfile
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
        app_instance = app.App()
        config.Config.instance().set_app_pointer(app_instance)
        app_instance.start_main_loop()
        del(app_instance)

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




