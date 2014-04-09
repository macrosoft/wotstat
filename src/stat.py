#!/usr/bin/python
# -*- coding: utf-8 -*-
import BigWorld
import ArenaType
import datetime
import json
import os
import re
from Account import Account
from account_helpers import BattleResultsCache
from items import vehicles as vehiclesWG
from gui.shared.utils.requesters import StatsRequester
from helpers import i18n
from notification.NotificationListView import NotificationListView
from messenger import MessengerEntry
from messenger.formatters.service_channel import BattleResultsFormatter
import threading
from Queue import Queue
from xml.dom import minidom
from debug_utils import *

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
        self.battleStats = {}
        self.cache = {}
        self.colors = {}
        self.config = {}
        self.expectedValues = {}
        self.values = {}
        self.battles = []
        self.message = ''
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
                if self.cache.get('date', '') == self.startDate or \
                    not self.config.get('dailyAutoReset', True):
                    if self.cache.get('players', {}).has_key(self.playerName):
                        self.battles = self.cache['players'][self.playerName]['battles']
                    invalidCache = False
        if invalidCache:
            self.cache = {}
        self.updateMessage()
        self.thread = threading.Thread(target=self.mainLoop)
        self.thread.setDaemon(True)
        self.thread.start()

    def save(self):
        statCache = open(self.statCacheFilePath, 'w')
        self.cache['date'] = self.startDate
        if not self.cache.has_key('players'):
            self.cache['players'] = {}
        if not self.cache['players'].has_key(self.playerName):
            self.cache['players'][self.playerName] = {}
        self.cache['players'][self.playerName]['battles'] = self.battles
        statCache.write(json.dumps(self.cache, sort_keys = True, indent = 4, separators=(',', ': ')))
        statCache.close()

    def createMessage(self):
        message = {
            'typeID': 1,
            'message': {
                'bgIcon': '',
                'defaultIcon': '',
                'savedID': 0,
                'timestamp': -1,
                'filters': [],
                'buttonsLayout': [],
                'message': self.message,
                'type': 'black',
                'icon': '../maps/icons/library/PersonalAchievementsIcon-1.png',
            },
            'hidingAnimationSpeed': 2000.0,
            'notify': True,
            'lifeTime': 6000.0,
            'entityID': 10,
            'auxData': ['GameGreeting']
        }
        return message

    def battleResultsCallback(self, responseCode, value = None, revision = 0):
        if responseCode < 0:
            self.battleResultsBusy.release()
            return
        if value['common']['guiType'] in self.config.get('ignoreBattleType', []):
            return
        vehicleCompDesc = value['personal']['typeCompDescr']
        vt = vehiclesWG.getVehicleType(vehicleCompDesc)
        win = 1 if int(value['personal']['team']) == int(value['common']['winnerTeam']) else 0
        battleTier = 1
        arenaUniqueID = value['arenaUniqueID']
        for key in value['vehicles'].keys():
            pTypeCompDescr = value['vehicles'][key]['typeCompDescr']
            pvt = vehiclesWG.getVehicleType(pTypeCompDescr)
            battleTier = max(battleTier, pvt.level)
            proceeds = value['personal']['credits'] - value['personal']['autoRepairCost'] -\
                       value['personal']['autoEquipCost'][0] - value['personal']['autoLoadCost'][0] -\
                       value['personal']['creditsContributionOut']
        battle = {
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
            'credits': proceeds,
            'battleTier': battleTier
        }
        self.battles.append(battle)
        self.save()
        self.updateMessage()
        battleStat = {}
        colors = {}
        self.calcWN8([battle], battleStat, colors)
        self.battleStats[arenaUniqueID] = {}
        self.battleStats[arenaUniqueID]['values'] = battleStat
        self.battleStats[arenaUniqueID]['colors'] = colors
        self.battleResultsBusy.release()

    def mainLoop(self):
        while True:
            arenaUniqueID = self.queue.get()
            stat.battleResultsAvailable.wait()
            self.battleResultsBusy.acquire()
            BigWorld.player().battleResultsCache.get(arenaUniqueID, self.battleResultsCallback)

    def refreshColorMacros(self, values, colors):
        if values['battlesCount'] == 0:
            for key in values.keys():
                colors[key] = '#FFFFFF'
            return
        for key in values.keys():
            if self.config['colors'].has_key(key):
                clrs = self.config['colors'][key]
                if values[key] <= clrs[0]['value']:
                    colors[key] = clrs[0]['color']
                elif values[key] >= clrs[-1]['value']:
                    colors[key] = clrs[-1]['color']
                else:
                    sVal = clrs[0]['value']
                    eVal = clrs[1]['value']
                    i = 1
                    while eVal < values[key]:
                        sVal = clrs[i]['value']
                        i += 1
                        eVal = clrs[i]['value']
                    val = float(values[key] - sVal)/(eVal - sVal)
                    colors[key] = gradColor(clrs[i - 1]['color'], clrs[i]['color'], val)
            else:
                colors[key] = '#FFFFFF'
    
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

    def calcWN8(self, battles, values, colors):
        values['battlesCount'] = len(battles)
        totalTier = 0
        totalBattleTier = 0
        valuesKeys = ['winsCount', 'totalDmg', 'totalFrag', 'totalSpot', 'totalDef', 'totalXP', 'totalOriginXP', 'credits']
        for key in valuesKeys:
            values[key] = 0
        expKeys = ['expDamage', 'expFrag', 'expSpot', 'expDef', 'expWinRate']
        expValues = {}
        for key in expKeys:
            expValues['total_' + key] = 0.0
        for battle in battles:
            values['winsCount'] += battle['win']
            values['totalDmg'] += battle['damage']
            values['totalFrag'] += battle['frag']
            values['totalSpot'] += battle['spot']
            values['totalDef'] += battle['def']
            values['totalXP'] += battle['xp']
            values['totalOriginXP'] += battle['originalXP']
            values['credits'] += battle['credits']
            totalTier += battle['tier']
            totalBattleTier += battle['battleTier']
            idNum = battle['idNum']
            if not self.expectedValues.has_key(idNum):
                self.calcExpected(idNum)
            expValues['total_expDamage'] += self.expectedValues[idNum]['expDamage']
            expValues['total_expFrag'] += self.expectedValues[idNum]['expFrag']
            expValues['total_expSpot'] += self.expectedValues[idNum]['expSpot']
            expValues['total_expDef'] += self.expectedValues[idNum]['expDef']
            expValues['total_expWinRate'] += self.expectedValues[idNum]['expWinRate']
        if values['battlesCount'] > 0:
            values['avgWinRate'] = float(values['winsCount'])/values['battlesCount']*100
            values['avgDamage'] = float(values['totalDmg'])/values['battlesCount']
            values['avgFrag'] = float(values['totalFrag'])/values['battlesCount']
            values['avgSpot'] = float(values['totalSpot'])/values['battlesCount']
            values['avgDef'] = float(values['totalDef'])/values['battlesCount']
            values['avgXP'] = int(values['totalOriginXP']/values['battlesCount'])
            values['avgCredits'] = int(values['credits']/values['battlesCount'])
            values['avgTier'] = round(float(totalTier)/values['battlesCount'], 1)
            values['avgBattleTier'] = round(float(totalBattleTier)/values['battlesCount'], 1)
            for key in expKeys:
                values[key] = expValues['total_' + key]/values['battlesCount']
        else:
            for key in ['avgWinRate', 'avgDamage', 'avgFrag', 'avgSpot', 'avgDef', 'avgXP', 'avgCredits', 'avgTier', 'avgBattleTier']:
                values[key] = 0
            for key in expKeys:
                values[key] = 1
        values['avgBattleTierDiff'] = values['avgBattleTier'] - values['avgTier']
        values['rDAMAGE'] = values['avgDamage']/values['expDamage']
        values['rSPOT'] = values['avgSpot']/values['expSpot']
        values['rFRAG'] = values['avgFrag']/values['expFrag']
        values['rDEF'] = values['avgDef']/values['expDef']
        values['rWIN'] = values['avgWinRate']/values['expWinRate']
        values['rWINc'] = max(0, (values['rWIN'] - 0.71)/(1 - 0.71))
        values['rDAMAGEc'] = max(0, (values['rDAMAGE'] - 0.22)/(1 - 0.22))
        values['rFRAGc'] = max(0, min(values['rDAMAGEc'] + 0.2, (values['rFRAG'] - 0.12)/(1 - 0.12)))
        values['rSPOTc'] = max(0, min(values['rDAMAGEc'] + 0.1, (values['rSPOT'] - 0.38)/(1 - 0.38)))
        values['rDEFc'] = max(0, min(values['rDAMAGEc'] + 0.1, (values['rDEF'] - 0.10)/(1 - 0.10)))
        values['WN8'] = 980*values['rDAMAGEc'] + 210*values['rDAMAGEc']*values['rFRAGc'] + \
            155*values['rFRAGc']*values['rSPOTc'] + 75*values['rDEFc']*values['rFRAGc'] + \
            145*min(1.8, values['rWINc'])
        values['XWN8'] = 100 if values['WN8'] > 3250 \
            else int(max(min(values['WN8']*(values['WN8']*(values['WN8']*(values['WN8']*(values['WN8']*\
            (0.0000000000000000000812*values['WN8'] + 0.0000000000000001616) - 0.000000000006736) +\
            0.000000028057) - 0.00004536) + 0.06563) - 0.01, 100), 0))
        values['WN8'] = int(values['WN8'])
        self.refreshColorMacros(values, colors)

    def updateMessage(self):
        self.calcWN8(self.battles, self.values, self.colors)
        msg = '\n'.join(self.config.get('template',''))
        for key in self.values.keys():
            if type(self.values[key]) is float:
                msg = msg.replace('{{%s}}' % key, str(round(self.values[key], 2)))
            else:
                msg = msg.replace('{{%s}}' % key, str(self.values[key]))
            msg = msg.replace('{{c:%s}}' % key, self.colors[key])
        self.message = msg

    def filterNotificationList(self, item):
        message = item.get('message', {}).get('message', '')
        if type(message) == str:
            msg = unicode(message, 'utf-8')
            for pattern in self.config.get('hideMessagePatterns', []):
                if re.search(pattern, msg, re.I):
                    return False
        return True

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

def new_nlv_populate(self):
    old_nlv_populate(self)
    self.as_appendMessageS(stat.createMessage())

NotificationListView._populate = new_nlv_populate

def new_nlv_setNotificationList(self):
    formedList = map(lambda item: item.getListVO(), self._model.collection.getListIterator())
    if len(stat.config.get('hideMessagePatterns', [])):
        formedList = filter(stat.filterNotificationList, formedList)
    self.as_setMessagesListS(formedList)

NotificationListView._NotificationListView__setNotificationList = new_nlv_setNotificationList

old_brf_format = BattleResultsFormatter.format

def new_brf_format(self, message, *args):
    result = old_brf_format(self, message, *args)
    arenaUniqueID = message.data.get('arenaUniqueID', 0)
    stat.queue.put(arenaUniqueID)
    if hasattr(BigWorld.player(), 'arena'):
        if BigWorld.player().arena.arenaUniqueID != arenaUniqueID:
            isWinner = message.data.get('isWinner', 0)
            battleEndedMessage = ''
            if isWinner < 0:
                battleEndedMessage = stat.config.get('battleEndedMessageDefeat', '')
            elif isWinner > 0:
                battleEndedMessage = stat.config.get('battleEndedMessageWin', '')
            else:
                battleEndedMessage = stat.config.get('battleEndedMessageDraw', '')
            battleEndedMessage = battleEndedMessage.encode('utf-8')
            vehicleCompDesc = message.data.get('vehTypeCompDescr', None)
            vt = vehiclesWG.getVehicleType(vehicleCompDesc)
            battleEndedMessage = battleEndedMessage.replace('{{vehicle}}', vt.shortUserString)
            arenaTypeID = message.data.get('arenaTypeID', 0)
            arenaType = ArenaType.g_cache[arenaTypeID]
            arenaName = i18n.makeString(arenaType.name)
            battleEndedMessage = battleEndedMessage.replace('{{map}}', arenaName)
            MessengerEntry.g_instance.gui.addClientMessage(battleEndedMessage)
    return result

BattleResultsFormatter.format = new_brf_format

stat = SessionStatistic()
