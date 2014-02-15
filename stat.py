#!/usr/bin/python
# -*- coding: utf-8 -*-

import BigWorld
from Account import Account
from adisp import process
from items import vehicles as vehicles_core
from gui.shared.utils.requesters import StatsRequester
from gui.shared import g_itemsCache
from notification.NotificationListView import NotificationListView
from messenger.formatters.service_channel import BattleResultsFormatter
from debug_utils import *

@process
def getDossier():
    stats = {}
    stats['credits'] = yield StatsRequester().getCredits()
    dossier = g_itemsCache.items.getAccountDossier().getTotalStats()
    stats['battlesCount'] = dossier.getBattlesCount()
    stats['winsCount'] = dossier.getWinsCount()
    stats['totalXP'] = dossier.getXP()
    stats['damageDealt'] = dossier.getDamageDealt()
    stats['fragsCount'] = dossier.getFragsCount()
    stats['spottedCount'] = dossier.getSpottedEnemiesCount()
    stats['dCapPoints'] = dossier.getDroppedCapturePoints()
    LOG_NOTE(stats)

old_onBecomePlayer = Account.onBecomePlayer

def new_onBecomePlayer(self):
    old_onBecomePlayer(self)
    pass

Account.onBecomePlayer = new_onBecomePlayer


old_nlv_populate = NotificationListView._populate

def new_nlv_populate(self, target = 'SummaryMessage'):
    old_nlv_populate(self)
    msg = {
        'type': 'black',
        'icon': '../maps/icons/library/PersonalAchievementsIcon-1.png',
        'message': 'Work in progress',
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
    getDossier()

NotificationListView._populate = new_nlv_populate

old_brf_format = BattleResultsFormatter.format

def new_brf_format(self, message, *args):
    old_brf_format(self, message, *args)
    vehicleCompDesc = message.data.get('vehTypeCompDescr', None)
    vt = vehicles_core.getVehicleType(vehicleCompDesc)
    LOG_NOTE(vt.name)

BattleResultsFormatter.format = new_brf_format

