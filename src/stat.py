#!/usr/bin/python
# -*- coding: utf-8 -*-
import BigWorld
import datetime
import json
import os
from Account import Account
from account_helpers import BattleResultsCache
from adisp import process
from items import vehicles as vehiclesWG
from gui.shared.utils.requesters import StatsRequester
from gui.shared import g_itemsCache
from notification.NotificationListView import NotificationListView
from messenger.formatters.service_channel import BattleResultsFormatter
from time import sleep
from threading import Thread
from Queue import Queue
from xml.dom import minidom
from debug_utils import *

@process
def getDossier(callback1, callback2 = None):
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
    callback1(stats)
    if callback2 is not None:
        callback2()

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

def hexToRgb(hex):
    return [int(hex[i:i+2], 16) for i in range(1,6,2)] 

def gradColor(startColor, endColor, val):
    start = hexToRgb(startColor)
    end = hexToRgb(endColor)
    grad = []
    for i in [0, 1, 2]:
        grad.append(start[i]*(1.0 - val) + end[i]*val)
    return '#%02x%02x%02x' % (grad[0], grad[1], grad[2])

class SessionStatistic(object):

    def __init__(self):
        self.queue = Queue()
        self.loaded = False
        self.cache = {}
        self.config = {}
        self.expectedValues = {}
        self.startValues = {}
        self.lastValues = {}
        self.values = {}
        self.colors = {}
        self.vehicles = []
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
                configFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_config.json')
                expectedValuesPath = os.path.join(path, 'scripts', 'client', 'mods', 'expected_tank_values.json')
                self.statCacheFilePath = os.path.join(path, 'scripts', 'client', 'mods', 'stat_cache.json')
                if os.path.isfile(configFilePath):
                    break
        with open(configFilePath) as configFileJson:
            self.config = json.load(configFileJson)
        with open(expectedValuesPath) as origExpectedValuesJson:
            origExpectedValues = json.load(origExpectedValuesJson)
            for tankValues in origExpectedValues['data']:
                idNum = tankValues.pop('IDNum')
                self.expectedValues[int(idNum)] = tankValues
        invalidCache = True
        if os.path.isfile(self.statCacheFilePath):
            with open(self.statCacheFilePath) as jsonCache:
                self.cache = json.load(jsonCache)
                if self.cache.get('date', '') == self.startDate:
                    if self.cache.get('players', {}).has_key(self.playerName):
                        self.startValues = self.cache['players'][self.playerName]['stats']
                        self.vehicles = self.cache['players'][self.playerName]['vehicles']
                    invalidCache = False
        if invalidCache:
            self.cache = {}
        if len(self.startValues) == 0:
            getDossier(self.startValues.update, self.save)
        self.thread = Thread(target=self.mainLoop)
        self.thread.setDaemon(True)
        self.thread.start()

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

    def mainLoop(self):
        arenaUniqueID = -1
        while True:
            if arenaUniqueID < 0:
                arenaUniqueID = self.queue.get()
            if not hasattr(BigWorld.player(), 'battleResultsCache'):
                sleep(1)
                LOG_NOTE('Zzz...')
                continue
            BigWorld.player().battleResultsCache.get(arenaUniqueID, battleResultsCallback)
            arenaUniqueID = -1

    def updateDossier(self):
        getDossier(self.lastValues.update)

    def refreshColorMacros(self):
        if self.values['battlesCount'] == 0:
            for key in self.values.keys():
                self.colors[key] = '#FFFFFF'
            return
        for key in self.values.keys():
            if self.config['colors'].has_key(key):
                clrs = self.config['colors'][key]
                if self.values[key] <= clrs[0]['value']:
                    self.colors[key] = clrs[0]['color']
                elif self.values[key] >= clrs[-1]['value']:
                    self.colors[key] = clrs[-1]['color']
                else:
                    sVal = clrs[0]['value']
                    eVal = clrs[1]['value']
                    i = 1
                    while eVal < self.values[key]:
                        sVal = clrs[i]['value']
                        i += 1
                        eVal = clrs[i]['value']
                    val = float(self.values[key] - sVal)/(eVal - sVal)
                    self.colors[key] = gradColor(clrs[i - 1]['color'], clrs[i]['color'], val)
            else:
                self.colors[key] = '#FFFFFF'
    
    def calcExpected(self, newIdNum):
        v = vehiclesWG.getVehicleType(newIdNum)
        newTier = v.level
        newType = set(vehiclesWG.VEHICLE_CLASS_TAGS.intersection(v.tags)).pop()
        if newTier < 1 or newTier > 10:
            newTier = 10
        tierExpected = {}
        tierExpectedCount = 0.0
        typeExpected = {}
        typeExpectedCount = 0.0
        for idNum in self.expectedValues:
            vt = vehiclesWG.getVehicleType(idNum)
            if vt.level == newTier:
                tierExpectedCount += 1
                vType = set(vehiclesWG.VEHICLE_CLASS_TAGS.intersection(vt.tags)).pop()
                if vType == newType:
                    typeExpectedCount += 1
                for key in self.expectedValues[idNum]:
                    tierExpected[key] = tierExpected.get(key, 0) + float(self.expectedValues[idNum].get(key, 0))
                    if vType == newType:
                        typeExpected[key] = typeExpected.get(key, 0) + float(self.expectedValues[idNum].get(key, 0))
        if typeExpectedCount > 0:
            for key in typeExpected:
                typeExpected[key] /= typeExpectedCount
            self.expectedValues[newIdNum] = typeExpected.copy()
            return
        for key in tierExpected:
            tierExpected[key] /= tierExpectedCount
        self.expectedValues[newIdNum] = tierExpected.copy()

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
            if not self.expectedValues.has_key(idNum):
                self.calcExpected(idNum)
            totalExp['total_avgTier'] += float(vehicle['tier'])
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
        self.values['rDAMAGE'] = self.values['avgDmg']/self.values['expDmg']
        self.values['rSPOT'] = self.values['avgSpot']/self.values['expSpot']
        self.values['rFRAG'] = self.values['avgFrag']/self.values['expFrag']
        self.values['rDEF'] = self.values['avgDef']/self.values['expDef']
        self.values['rWIN'] = self.values['avgWinRate']/self.values['expWinRate']
        self.values['rWINc'] = max(0, (self.values['rWIN'] - 0.71)/(1 - 0.71))
        self.values['rDAMAGEc'] = max(0, (self.values['rDAMAGE'] - 0.22)/(1 - 0.22))
        self.values['rFRAGc'] = max(0, min(self.values['rDAMAGEc'] + 0.2, (self.values['rFRAG'] - 0.12)/(1 - 0.12)))
        self.values['rSPOTc'] = max(0, min(self.values['rDAMAGEc'] + 0.1, (self.values['rSPOT'] - 0.38)/(1 - 0.38)))
        self.values['rDEFc'] = max(0, min(self.values['rDAMAGEc'] + 0.1, (self.values['rDEF'] - 0.10)/(1 - 0.10)))
        self.values['WN8'] = 980*self.values['rDAMAGEc'] + 210*self.values['rDAMAGEc']*self.values['rFRAGc'] + \
            155*self.values['rFRAGc']*self.values['rSPOTc'] + 75*self.values['rSPOTc']*self.values['rFRAGc'] + \
            145*min(1.8, self.values['rWINc'])
        self.values['XWN8'] = 100 if self.values['WN8'] > 3250 \
            else int(max(min(self.values['WN8']*(self.values['WN8']*\
            (self.values['WN8']*(self.values['WN8']*(self.values['WN8']*\
            (0.0000000000000000000812*self.values['WN8'] + 0.0000000000000001616) - \
            0.000000000006736) + 0.000000028057) - 0.00004536) + 0.06563) - 0.01, 100), 0))
        self.values['WN8'] = int(self.values['WN8'])
        self.refreshColorMacros()

    def printMessage(self):
        self.recalc()
        msg = '\n'.join(self.config.get('template',''))
        for key in self.values.keys():
            if type(self.values[key]) is float:
                msg = msg.replace('{{%s}}' % key, str(round(self.values[key], 2)))
            else:
                msg = msg.replace('{{%s}}' % key, str(self.values[key]))
            msg = msg.replace('{{c:%s}}' % key, self.colors[key])
        return msg


old_onBecomePlayer = Account.onBecomePlayer

def battleResultsCallback(responseCode, value = None, revision = 0):
    vehicleCompDesc = value['personal']['typeCompDescr']
    vt = vehiclesWG.getVehicleType(vehicleCompDesc)
    win = 1 if int(value['personal']['team']) == int(value['common']['winnerTeam']) else 0
    stat.vehicles.append({
        'idNum': vehicleCompDesc,
        'name': vt.name,
        'tier': vt.level,
        'win': win,
        'damage': value['personal']['damageDealt'],
        'frag': value['personal']['kills'],
        'spot': value['personal']['spotted'],
        'def': value['personal']['droppedCapturePoints']
        })
    stat.save()
    LOG_NOTE(value)

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
    arenaUniqueID = message.data.get('arenaUniqueID', 0)
    stat.queue.put(arenaUniqueID)
    return result

BattleResultsFormatter.format = new_brf_format

stat = SessionStatistic()
