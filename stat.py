#!/usr/bin/python
# -*- coding: utf-8 -*-

import BigWorld
from Account import Account
from notification.NotificationListView import NotificationListView
from debug_utils import *

old_onBecomePlayer = Account.onBecomePlayer

def new_onBecomePlayer(self):
    old_onBecomePlayer(self)
    pass

Account.onBecomePlayer = new_onBecomePlayer


old_populate = NotificationListView._populate

def new_populate(self, target = 'SummaryMessage'):
    old_populate(self)
    LOG_NOTE("test")
    msg = {
        'type': 'red',
        'icon': '../maps/icons/library/PersonalAchievementsIcon-1.png',
        'message': 'Hello World!',
        'showMore': {
            'command': 'stat',
            'enabled': False,
            'param': 'None'
        }
    }
    message = {
        'message': msg,
        'priority': True,
        'notify': False,
        'auxData': ['GameGreeting']
    }
    self.as_appendMessageS(message)

NotificationListView._populate = new_populate
