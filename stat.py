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
def getDossier(callback):
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
    callback(stats)

def createMessage(text):
    msg = {
        'type': 'black',
        'icon': '../maps/icons/library/PersonalAchievementsIcon-1.png',
        'message': text,
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
    return message

class SessionStatistic(object):       
    def __init__(self):
        self.values = {}
        
    def reset(self):
        selft.values = {
            'startCredits' : 0,
            'startTotalXp' : 0,
            'startBattlesCount' : 0,
            'startWinsCount' : 0,
            'startDamageDealt' : 0,
            'startFragsCount' : 0,
            'startSpottedCount' : 0,
            'startDCapPoints' : 0,
            'lastCredits' : 0,
            'lastTotalXp' : 0,
            'lastBattlesCount' : 0,
            'lastWinsCount' : 0,
            'lastDamageDealt' : 0,
            'lastFragsCount' : 0,
            'lastSpottedCount' : 0,
            'lastDCapPoints' : 0,
        }

    def initDossier(self, dossier):
        self.values['startCredits'] = dossier['credits']
        self.values['startTotalXp'] = dossier['totalXP']
        self.values['startBattlesCount'] = dossier['battlesCount']
        self.values['startWinsCount'] = dossier['winsCount']
        self.values['startDamageDealt'] = dossier['damageDealt']
        self.values['startFragsCount'] = dossier['fragsCount']
        self.values['startSpottedCount'] = dossier['spottedCount']
        self.values['startDCapPoints'] = dossier['dCapPoints']

    def load(self):
        getDossier(self.initDossier)

    def getValue(self, name, default = 0):
        return self.values.get(name, default)

    def getValue(self, name, default = 0):
        return str(self.values.get(name, default))

old_onBecomePlayer = Account.onBecomePlayer

def new_onBecomePlayer(self):
    old_onBecomePlayer(self)
    stat.load()

Account.onBecomePlayer = new_onBecomePlayer


old_nlv_populate = NotificationListView._populate

def new_nlv_populate(self, target = 'SummaryMessage'):
    old_nlv_populate(self)
    msg = createMessage('Credits: ' + stat.getValue('startCredits'))
    self.as_appendMessageS(msg)

NotificationListView._populate = new_nlv_populate

old_brf_format = BattleResultsFormatter.format

def new_brf_format(self, message, *args):
    old_brf_format(self, message, *args)
    vehicleCompDesc = message.data.get('vehTypeCompDescr', None)
    LOG_NOTE(vehicleCompDesc)
    vt = vehicles_core.getVehicleType(vehicleCompDesc)
    LOG_NOTE(vt.shortUserString)

BattleResultsFormatter.format = new_brf_format

stat = SessionStatistic()
