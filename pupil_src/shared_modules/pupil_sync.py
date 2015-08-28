'''
(*)~----------------------------------------------------------------------------------
 Pupil - eye tracking platform
 Copyright (C) 2012-2015  Pupil Labs

 Distributed under the terms of the CC BY-NC-SA License.
 License details are in the file license.txt, distributed as part of this software.
----------------------------------------------------------------------------------~(*)
'''


from plugin import Plugin

from pyglui import ui
import zmq
from pyre import Pyre
from pyre import zhelper
from time import sleep
import logging
logger = logging.getLogger(__name__)


start_rec = "START_REC:"
stop_rec = "STOP_REC:"
sync_time = "SYNC:"



class Pupil_Sync(Plugin):
    """Synchonize behaviour of Pupil captures
        across the local network
    """
    def __init__(self, g_pool,name='unnamed Pupil',group='default group'):
        super(Pupil_Sync, self).__init__(g_pool)
        self.order = .01 #excecute first
        self.name = name
        self.group = group
        self.group_members = {}
        self.menu = None
        self.group_menu = None

        self.context = zmq.Context()
        self.thread_pipe = zhelper.zthread_fork(self.context, self.thread_loop)


    def init_gui(self):
        help_str = "Synchonize behaviour of Pupil captures across the local network."
        self.menu = ui.Growing_Menu('Pupil Sync')
        self.menu.append(ui.Info_Text(help_str))
        self.menu.append(ui.Button('close Plugin',self.close))
        self.menu.append(ui.Text_Input('name',self,setter=self.set_name,label='Name'))
        self.menu.append(ui.Text_Input('group',self,setter=self.set_group,label='Group'))
        help_str = "Before starting a recording. Make sure to sync the timebase of all Pupils to one master Pupil by clicking the bottom below. This will apply this Pupil's timebase to all of its group."
        self.menu.append(ui.Info_Text(help_str))
        self.menu.append(ui.Button('sync time for all Pupils',self.set_sync))
        self.group_menu = ui.Growing_Menu('Other Pupils')
        self.menu.append(self.group_menu)
        self.g_pool.sidebar.append(self.menu)
        self.update_gui()

    def update_gui(self):
        if self.group_menu:
            self.group_menu.elements[:] = []
            for uid in self.group_members.keys():
                self.group_menu.append(ui.Info_Text("%s"%self.group_members[uid]))

    def set_name(self,new_name):
        self.name = new_name
        if self.thread_pipe:
            self.thread_pipe.send("EXIT_THREAD".encode('utf_8'))
            while self.thread_pipe:
                sleep(.01)
        self.thread_pipe = zhelper.zthread_fork(self.context, self.thread_loop)

    def set_group(self,new_name):
        self.group = new_name
        if self.thread_pipe:
            self.thread_pipe.send("EXIT_THREAD".encode('utf_8'))
            while self.thread_pipe:
                sleep(.01)
        self.group_members = {}
        self.update_gui()
        self.thread_pipe = zhelper.zthread_fork(self.context, self.thread_loop)

    def set_sync(self):

        ok_to_change = True
        for p in self.g_pool.plugins:
            if p.class_name == 'Recorder':
                if p.running:
                    ok_to_change = False
        if ok_to_change:
            self.thread_pipe.send(sync_time+'0.0')
            self.g_pool.timebase.value = 0.0
            logger.info("New timebase set to %s all timestamps will count from here now."%self.g_pool.timebase.value)
        else:
            logger.warning("Request to change timebase during recording ignored. Turn of recording first.")


    def close(self):
        self.alive = False

    def deinit_gui(self):
        if self.menu:
            self.g_pool.sidebar.remove(self.menu)
            self.menu = None



    def thread_loop(self,context,pipe):
        n = Pyre(self.name)
        n.join(self.group)
        n.start()

        poller = zmq.Poller()
        poller.register(pipe, zmq.POLLIN)
        logger.debug(n.socket())
        poller.register(n.socket(), zmq.POLLIN)
        while(True):
            try:
                items = dict(poller.poll())
            except zmq.ZMQError:
                break
            # print(n.socket(), items)
            if pipe in items and items[pipe] == zmq.POLLIN:
                message = pipe.recv()
                # message to quit
                if message.decode('utf-8') == "EXIT_THREAD":
                    break
                logger.debug("Emitting to '%s' to '%s' " %(message,self.group))
                n.shouts(self.group, message)
            if n.socket() in items and items[n.socket()] == zmq.POLLIN:
                cmds = n.recv()
                msg_type = cmds.pop(0)
                msg_type = msg_type.decode('utf-8')
                if msg_type == "SHOUT":
                    uid,name,group,msg = cmds
                    logger.debug("'%s' shouts '%s'."%(name,msg))
                    if start_rec in msg :
                        session_name = msg.replace(start_rec,'')
                        self.notify_all({'name':'rec_should_start','session_name':session_name})
                    elif stop_rec in msg:
                        self.notify_all({'name':'rec_should_stop'})
                    elif sync_time in msg:
                        timebase = float(msg.replace(sync_time,''))
                        ok_to_change = True
                        for p in self.g_pool.plugins:
                            if p.class_name == 'Recorder':
                                if p.running:
                                    ok_to_change = False
                        if ok_to_change:
                            self.g_pool.timebase.value = timebase
                            logger.info("New timebase set to %s all timestamps will count from here now."%self.g_pool.timebase.value)
                        else:
                            logger.warning("Request to change timebase during recording ignored. Turn of recording first.")

                elif msg_type == "ENTER":
                    uid,name,headers,ip = cmds
                elif msg_type == "JOIN":
                    uid,name,group = cmds
                    if group == self.group:
                        self.group_members[uid] = name
                        self.update_gui()
                elif msg_type == "EXIT":
                    uid,name = cmds
                    try:
                        del self.group_members[uid]
                    except KeyError:
                        pass
                    else:
                        self.update_gui()
                elif msg_type == "LEAVE":
                    uid,name,group = cmds
                elif msg_tpye == "WHISPER":
                    pass

        logger.debug('thread_loop closing.')
        self.thread_pipe = None
        n.stop()


    def on_notify(self,notification):
        if notification['name'] == 'rec_started' and notification['network_propagate']:
            self.thread_pipe.send(start_rec+notification['session_name'])
        if notification['name'] == 'rec_stopped' and notification['network_propagate']:
            self.thread_pipe.send(stop_rec)

    def get_init_dict(self):
        return {'name':self.name,'group':self.group}

    def cleanup(self):
        """gets called when the plugin get terminated.
           This happens either volunatily or forced.
        """
        self.deinit_gui()
        self.thread_pipe.send("EXIT_THREAD".encode('utf_8'))
        while self.thread_pipe:
            sleep(.01)
        self.context.destroy()

