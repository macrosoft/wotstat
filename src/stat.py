#!/usr/bin/python
# -*- coding: utf-8 -*-
import BigWorld
import datetime
import json
import os
from Account import Account
from account_helpers import BattleResultsCache
from items import vehicles as vehiclesWG
from gui.shared.utils.requesters import StatsRequester
from notification.NotificationListView import NotificationListView
from messenger.formatters.service_channel import BattleResultsFormatter
from time import sleep
import threading
from Queue import Queue
from xml.dom import minidom
from debug_utils import *

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
        self.values = {}
        self.colors = {}
        self.battles = []
        self.playerName = ''
        self.battleResultsAvailable = threading.Event()
        self.battleResultsAvailable.clear()
        self.battleResultsBusy = threading.Lock()
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
                idNum = int(tankValues.pop('IDNum'))
                self.expectedValues[idNum] = {}
                for key in ['expDamage', 'expFrag', 'expSpot', 'expDef', 'expWinRate']:
                    self.expectedValues[idNum][key] = float(tankValues[key])
        invalidCache = True
        if os.path.isfile(self.statCacheFilePath):
            with open(self.statCacheFilePath) as jsonCache:
                self.cache = json.load(jsonCache)
                if self.cache.get('date', '') == self.startDate:
                    if self.cache.get('players', {}).has_key(self.playerName):
                        self.battles = self.cache['players'][self.playerName]['battles']
                    invalidCache = False
        if invalidCache:
            self.cache = {}
        self.thread = threading.Thread(target=self.mainLoop)
        self.thread.setDaemon(True)
        self.thread.start()

    def save(self):
        if (len(self.battles) == 0):
            return
        statCache = open(self.statCacheFilePath, 'w')
        self.cache['date'] = self.startDate
        if not self.cache.has_key('players'):
            self.cache['players'] = {}
        if not self.cache['players'].has_key(self.playerName):
            self.cache['players'][self.playerName] = {}
        self.cache['players'][self.playerName]['battles'] = self.battles
        statCache.write(json.dumps(self.cache))
        statCache.close()

    def battleResultsCallback(self, responseCode, value = None, revision = 0):
        if responseCode < 0:
            self.battleResultsBusy.release()
            return
        vehicleCompDesc = value['personal']['typeCompDescr']
        vt = vehiclesWG.getVehicleType(vehicleCompDesc)
        win = 1 if int(value['personal']['team']) == int(value['common']['winnerTeam']) else 0
        battleTier = 1
        for key in value['vehicles'].keys():
            pTypeCompDescr = value['vehicles'][key]['typeCompDescr']
            pvt = vehiclesWG.getVehicleType(pTypeCompDescr)
            battleTier = max(battleTier, pvt.level)
        self.battles.append({
            'idNum': vehicleCompDesc,
            'name': vt.name,
            'tier': vt.level,
            'win': win,
            'damage': value['personal']['damageDealt'],
            'frag': value['personal']['kills'],
            'spot': value['personal']['spotted'],
            'def': value['personal']['droppedCapturePoints'],
            'xp': value['personal']['xp'],
            'originalXP': value['personal']['originalXP'],
            'credits': value['personal']['credits'],
            'battleTier': battleTier
        })
        self.save()
        LOG_NOTE(value)
        self.battleResultsBusy.release()

    def mainLoop(self):
        while True:
            arenaUniqueID = self.queue.get()
            stat.battleResultsAvailable.wait()
            self.battleResultsBusy.acquire()
            BigWorld.player().battleResultsCache.get(arenaUniqueID, self.battleResultsCallback)

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
                    tierExpected[key] = tierExpected.get(key, 0) + self.expectedValues[idNum].get(key, 0.0)
                    if vType == newType:
                        typeExpected[key] = typeExpected.get(key, 0) + self.expectedValues[idNum].get(key, 0.0)
        if typeExpectedCount > 0:
            for key in typeExpected:
                typeExpected[key] /= typeExpectedCount
            self.expectedValues[newIdNum] = typeExpected.copy()
            return
        for key in tierExpected:
            tierExpected[key] /= tierExpectedCount
        self.expectedValues[newIdNum] = tierExpected.copy()

    def recalc(self):
        self.values['battlesCount'] = len(self.battles)
        valuesKeys = ['winsCount', 'totalDmg', 'totalFrag', 'totalSpot', 'totalDef', 'totalTier', 'totalBattleTier', 'totalXP', 'totalOriginXP', 'credits']
        for key in valuesKeys:
            self.values[key] = 0
        expKeys = ['expDamage', 'expFrag', 'expSpot', 'expDef', 'expWinRate']
        expValues = {}
        for key in expKeys:
            expValues['total_' + key] = 0.0
        for battle in self.battles:
            self.values['winsCount'] += battle['win']
            self.values['totalDmg'] += battle['damage']
            self.values['totalFrag'] += battle['frag']
            self.values['totalSpot'] += battle['spot']
            self.values['totalDef'] += battle['def']
            self.values['totalXP'] += battle['xp']
            self.values['totalOriginXP'] += battle['originalXP']
            self.values['credits'] += battle['credits']
            self.values['totalTier'] += battle['tier']
            self.values['totalBattleTier'] += battle['battleTier']
            idNum = battle['idNum']
            if not self.expectedValues.has_key(idNum):
                self.calcExpected(idNum)
            expValues['total_expDamage'] += self.expectedValues[idNum]['expDamage']
            expValues['total_expFrag'] += self.expectedValues[idNum]['expFrag']
            expValues['total_expSpot'] += self.expectedValues[idNum]['expSpot']
            expValues['total_expDef'] += self.expectedValues[idNum]['expDef']
            expValues['total_expWinRate'] += self.expectedValues[idNum]['expWinRate']
        if self.values['battlesCount'] > 0:
            self.values['avgWinRate'] = float(self.values['winsCount'])/self.values['battlesCount']*100
            self.values['avgDamage'] = float(self.values['totalDmg'])/self.values['battlesCount']
            self.values['avgFrag'] = float(self.values['totalFrag'])/self.values['battlesCount']
            self.values['avgSpot'] = float(self.values['totalSpot'])/self.values['battlesCount']
            self.values['avgDef'] = float(self.values['totalDef'])/self.values['battlesCount']
            self.values['avgXP'] = int(self.values['totalOriginXP']/self.values['battlesCount'])
            self.values['avgCredits'] = int(self.values['credits']/self.values['battlesCount'])
            self.values['avgTier'] = round(float(self.values['totalTier'])/self.values['battlesCount'], 1)
            self.values['avgBattleTier'] = round(float(self.values['totalBattleTier'])/self.values['battlesCount'], 1)
            for key in expKeys:
                self.values[key] = expValues['total_' + key]/self.values['battlesCount']
        else:
            for key in ['avgWinRate', 'avgDamage', 'avgFrag', 'avgSpot', 'avgDef', 'avgXP', 'avgCredits', 'avgTier', ]:
                self.values[key] = 0
            for key in expKeys:
                self.values[key] = 1
        self.values['rDAMAGE'] = self.values['avgDamage']/self.values['expDamage']
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
            155*self.values['rFRAGc']*self.values['rSPOTc'] + 75*self.values['rDEFc']*self.values['rFRAGc'] + \
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

def new_onBecomePlayer(self):
    old_onBecomePlayer(self)
    stat.battleResultsAvailable.set()
    stat.load()

Account.onBecomePlayer = new_onBecomePlayer


old_onBecomeNonPlayer = Account.onBecomeNonPlayer

def new_onBecomeNonPlayer(self):
    stat.battleResultsAvailable.clear()
    old_onBecomeNonPlayer(self)

Account.onBecomeNonPlayer = new_onBecomeNonPlayer

old_nlv_populate = NotificationListView._populate

def new_nlv_populate(self, target = 'SummaryMessage'):
    old_nlv_populate(self)
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
