#!/usr/bin/python
# -*- coding: utf-8 -*-
import BigWorld
import datetime
import json
import os
from Account import Account
from adisp import process
from items import vehicles as vehicles_core
from gui.shared.utils.requesters import StatsRequester
from gui.shared import g_itemsCache
from notification.NotificationListView import NotificationListView
from messenger.formatters.service_channel import BattleResultsFormatter
from xml.dom import minidom
from debug_utils import *

@process
def getDossier(callback):
    stats = {}
    stats['credits'] = yield StatsRequester().getCredits()
    yield g_itemsCache.update(6)
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
        self.loaded = False
        self.startValues = {}
        self.lastValues = {}
        self.values = {}
        self.vehicles = []
        self.template = ''
        self.playerName = ''
        if datetime.datetime.now().hour >= 4:
            self.startDate = datetime.date.today().strftime('%Y-%m-%d')
        else:
            self.startDate = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        getDossier(self.startValues.update)
        self.playerName = BigWorld.player().name
        path_items = minidom.parse(os.path.join(os.getcwd(), 'paths.xml')).getElementsByTagName('Path')
        for root in path_items:
            path = os.path.join(os.getcwd(), root.childNodes[0].data)
            if os.path.isdir(path):
                templateFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_template.txt')
                self.statCacheFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_cache.json')
                if os.path.isfile(templateFilePath):
                    templateFile = open(templateFilePath, 'r')
                    self.template = str(templateFile.read())
                    break

    def save(self):
        statCache = open(self.statCacheFilePath, 'w')
        statCache.write(json.dumps({
            'date': self.startDate,
            'players': {
                self.playerName: {
                    "stats": self.startValues,
                    "vehicles": self.vehicles
                }
            }
        }))
        statCache.close()

    def addVehicle(self, idNum, name, tier):
        self.vehicles.append({
            'idNum': idNum,
            'name': name,
            'tier': tier
        })

    def updateDossier(self):
        getDossier(self.lastValues.update)

    def recalc(self):
        for key in self.startValues.keys():
            self.values[key] = self.lastValues[key] - self.startValues[key]

    def printMessage(self):
        self.recalc()
        return self.template % self.values


old_onBecomePlayer = Account.onBecomePlayer

def new_onBecomePlayer(self):
    old_onBecomePlayer(self)
    stat.load()

Account.onBecomePlayer = new_onBecomePlayer


old_nlv_populate = NotificationListView._populate

def new_nlv_populate(self, target = 'SummaryMessage'):
    old_nlv_populate(self)
    stat.updateDossier()
    msg = createMessage(stat.printMessage())
    self.as_appendMessageS(msg)

NotificationListView._populate = new_nlv_populate

old_brf_format = BattleResultsFormatter.format

def new_brf_format(self, message, *args):
    result = old_brf_format(self, message, *args)
    vehicleCompDesc = message.data.get('vehTypeCompDescr', None)
    vt = vehicles_core.getVehicleType(vehicleCompDesc)
    stat.addVehicle(vehicleCompDesc, vt.name, vt.level)
    stat.save()
    return result

BattleResultsFormatter.format = new_brf_format

stat = SessionStatistic()
