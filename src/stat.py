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
        self.cache = {}
        self.expectedValues = {}
        self.startValues = {}
        self.lastValues = {}
        self.values = {}
        self.vehicles = []
        self.template = ''
        self.playerName = ''
        self.startDate = datetime.date.today().strftime('%Y-%m-%d') \
            if datetime.datetime.now().hour >= 4 \
            else (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        self.playerName = BigWorld.player().name
        path_items = minidom.parse(os.path.join(os.getcwd(), 'paths.xml')).getElementsByTagName('Path')
        for root in path_items:
            path = os.path.join(os.getcwd(), root.childNodes[0].data)
            if os.path.isdir(path):
                templateFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_template.txt')
                expectedValuesPath = os.path.join(path, 'scripts', 'client', 'mods', 'expected_tank_values.json')
                self.statCacheFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_cache.json')
                if os.path.isfile(templateFilePath):
                    break
        templateFile = open(templateFilePath, 'r')
        self.template = str(templateFile.read())
        with open(expectedValuesPath) as origExpectedValuesJson:
            origExpectedValues = json.load(origExpectedValuesJson)
            for tankValues in origExpectedValues['data']:
                idNum = tankValues.pop('IDNum')
                self.expectedValues[int(idNum)] = tankValues
        invalidCache = True
        if os.path.isfile(self.statCacheFilePath):
            with open(self.statCacheFilePath) as jsonCache:
                self.cache = json.load(jsonCache)
                if self.cache['date'] == self.startDate:
                    self.startValues = self.cache['players'][self.playerName]['stats']
                    self.vehicles = self.cache['players'][self.playerName]['vehicles']
                    invalidCache = False
        if invalidCache:
            self.cache = {}
            getDossier(self.startValues.update)

    def save(self):
        if (len(self.startValues) == 0):
            return
        statCache = open(self.statCacheFilePath, 'w')
        self.cache['date'] = self.startDate
        if not self.cache.has_key('players'):
            self.cache['players'] = {}
        if not self.cache['players'].has_key(self.playerName):
            self.cache['players'][self.playerName] = {}
        self.cache['players'][self.playerName]['stats'] = self.startValues
        self.cache['players'][self.playerName]['vehicles'] = self.vehicles
        statCache.write(json.dumps(self.cache))
        statCache.close()

    def addVehicle(self, idNum, name, tier):
        self.vehicles.append({'idNum': idNum, 'name': name, 'tier': tier})

    def updateDossier(self):
        getDossier(self.lastValues.update)

    def recalc(self):
        for key in self.startValues.keys():
            self.values[key] = self.lastValues[key] - self.startValues[key]
        self.values['battlesCount'] = max(self.values['battlesCount'], 0)
        if self.values['battlesCount'] > 0:
            self.values['avgWinRate'] = float(self.values['winsCount'])/self.values['battlesCount']*100
            self.values['avgDmg'] = float(self.values['damageDealt'])/self.values['battlesCount']
            self.values['avgFrag'] = float(self.values['fragsCount'])/self.values['battlesCount']
            self.values['avgSpot'] = float(self.values['spottedCount'])/self.values['battlesCount']
            self.values['avgDef'] = float(self.values['dCapPoints'])/self.values['battlesCount']
            self.values['avgXP'] = int(self.values['totalXP']/self.values['battlesCount'])
            self.values['avgCredits'] = int(self.values['credits']/self.values['battlesCount'])
        else:
            for key in ['avgWinRate', 'avgDmg', 'avgFrag', 'avgSpot', 'avgDef', 'avgXP', 'avgCredits']:
                self.values[key] = 0
        while len(self.vehicles) > self.values['battlesCount']:
            self.vehicles.pop(0)
        vehiclesKeys = ['avgTier', 'expDmg', 'expFrag', 'expSpot', 'expDef', 'expWinRate']
        totalExp = {}
        for key in vehiclesKeys:
            totalExp['total_' + key] = 0
        for vehicle in self.vehicles:
            idNum = vehicle['idNum']
            totalExp['total_avgTier'] += vehicle['tier']
            totalExp['total_expDmg'] += float(self.expectedValues[idNum]['expDamage'])
            totalExp['total_expFrag'] += float(self.expectedValues[idNum]['expFrag'])
            totalExp['total_expSpot'] += float(self.expectedValues[idNum]['expSpot'])
            totalExp['total_expDef'] += float(self.expectedValues[idNum]['expDef'])
            totalExp['total_expWinRate'] += float(self.expectedValues[idNum]['expWinRate'])
        if len(self.vehicles) > 0:
            for key in vehiclesKeys:
                self.values[key] = totalExp['total_' + key]/len(self.vehicles)
        else:
            self.values['avgTier'] = 0
            self.values['expDmg'] = max(1, self.values['avgDmg'])
            self.values['expFrag'] = max(1, self.values['avgFrag'])
            self.values['expSpot'] = max(1, self.values['avgSpot'])
            self.values['expDef'] = max(1, self.values['avgDef'])
            self.values['expWinRate'] = max(1, self.values['avgWinRate'])
        LOG_NOTE(self.values)

    def printMessage(self):
        self.recalc()
        msg = self.template
        for key in self.values.keys():
            if type(self.values[key]) is float:
                msg = msg.replace('{{%s}}' % key, str(round(self.values[key], 2)))
            else:
                msg = msg.replace('{{%s}}' % key, str(self.values[key]))
        return msg


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
