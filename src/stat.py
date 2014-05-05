#!/usr/bin/python
# -*- coding: utf-8 -*-
import BigWorld
import AccountCommands
import ArenaType
import codecs
import datetime
import json
import math
import os
import re
import ResMgr
import threading
from Account import Account
from account_helpers import BattleResultsCache
from items import vehicles as vehiclesWG
from functools import partial
from gui.shared.utils.requesters import StatsRequester
from helpers import i18n
from notification.NotificationListView import NotificationListView
from messenger import MessengerEntry
from messenger.formatters.service_channel import BattleResultsFormatter
from Queue import Queue
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
        self.cacheVersion = 4
        self.queue = Queue()
        self.loaded = False
        self.configIsValid = True
        self.battleStats = {}
        self.cache = {}
        self.gradient = {}
        self.palette = {}
        self.config = {}
        self.expectedValues = {}
        self.values = {}
        self.battles = []
        self.message = ''
        self.playerName = ''
        self.startDate = None
        self.battleResultsAvailable = threading.Event()
        self.battleResultsAvailable.clear()
        self.battleResultsBusy = threading.Lock()
        self.thread = threading.Thread(target=self.mainLoop)
        self.thread.setDaemon(True)
        self.thread.start()

    def load(self):
        if self.loaded and self.playerName == BigWorld.player().name:
            return
        self.loaded = True
        self.battles = []
        self.playerName = BigWorld.player().name
        res = ResMgr.openSection('../paths.xml')
        sb = res['Paths']
        vals = sb.values()
        for vl in vals:
            path = vl.asString + '/scripts/client/mods/'
            if os.path.isdir(path):
                self.configFilePath = path + 'stat_config.json'
                self.statCacheFilePath = path + 'stat_cache.json'
                expectedValuesPath = path + 'expected_tank_values.json'
                if os.path.isfile(self.configFilePath):
                    break
        self.readConfig()
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
                self.startDate = self.cache.get('date', self.getWorkDate())
                if self.cache.get('version', 0) == self.cacheVersion and \
                    (self.startDate == self.getWorkDate() or \
                    not self.config.get('dailyAutoReset', True)):
                    if self.cache.get('players', {}).has_key(self.playerName):
                        self.battles = self.cache['players'][self.playerName]['battles']
                    invalidCache = False
        if invalidCache:
            self.cache = {}
        self.updateMessage()

    def readConfig(self):
        with codecs.open(self.configFilePath, 'r', 'utf-8-sig') as configFileJson:
            try:
                self.config = json.load(configFileJson)
                self.configIsValid = True
            except ValueError:
                print 'load stat_config.json has failed'
                self.config = {}
                self.configIsValid = False

    def getWorkDate(self):
        return datetime.date.today().strftime('%Y-%m-%d') \
            if datetime.datetime.now().hour >= self.config.get('dailyAutoResetHour', 4) \
            else (datetime.date.today() - datetime.timedelta(days = 1)).strftime('%Y-%m-%d')

    def save(self):
        statCache = open(self.statCacheFilePath, 'w')
        self.cache['version'] = self.cacheVersion
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
                'bgIcon':  self.config.get('bgIcon', ''),
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
            'entityID': 99999,
            'auxData': ['GameGreeting']
        }
        if self.config.get('showResetButton', False):
            message['message']['buttonsLayout'].append({
                'action': 'wotstatReset',
                'type': 'submit',
                'label': self.config.get('textResetButton', 'Reset')
            })
        return message

    def addLaterArenaUniqueID(self, arenaUniqueID):
        self.queue.put(arenaUniqueID)

    def battleResultsCallback(self, arenaUniqueID, responseCode, value = None, revision = 0):
        if responseCode == AccountCommands.RES_NON_PLAYER or responseCode == AccountCommands.RES_COOLDOWN:
            addArenaUniqueID = partial(self.addLaterArenaUniqueID, arenaUniqueID)
            BigWorld.callback(1.0, addArenaUniqueID)
            self.battleResultsBusy.release()
            return
        if responseCode < 0 or value['common']['guiType'] in self.config.get('ignoreBattleType', []):
            self.battleResultsBusy.release()
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
                       value['personal']['autoEquipCost'][0] - value['personal']['autoLoadCost'][0]
        battle = {
            'idNum': vehicleCompDesc,
            'name': vt.name,
            'tier': vt.level,
            'win': win,
            'damage': value['personal']['damageDealt'],
            'frag': value['personal']['kills'],
            'spot': value['personal']['spotted'],
            'def': value['personal']['droppedCapturePoints'],
            'cap': value['personal']['capturePoints'],
            'shots': value['personal']['shots'],
            'hits': value['personal']['directHits'],
            'pierced': value['personal']['piercings'],
            'xp': value['personal']['xp'],
            'originalXP': value['personal']['originalXP'],
            'credits': proceeds,
            'autoRepair': value['personal']['autoRepairCost'],
            'autoEquip': value['personal']['autoEquipCost'][0],
            'autoLoad': value['personal']['autoLoadCost'][0],
            'gold': value['personal']['gold'] - value['personal']['autoEquipCost'][1] - value['personal']['autoLoadCost'][1],
            'battleTier': battleTier,
            'assist': value['personal']['damageAssistedRadio'] + value['personal']['damageAssistedTrack']
        }
        if self.config.get('dailyAutoReset', True) and self.startDate != stat.getWorkDate():
            self.reset()
        self.battles.append(battle)
        self.save()
        self.updateMessage()
        battleStat = {}
        gradient = {}
        palette = {}
        self.calcWN8([battle], battleStat, gradient, palette)
        self.battleStats[arenaUniqueID] = {}
        self.battleStats[arenaUniqueID]['values'] = battleStat
        self.battleStats[arenaUniqueID]['gradient'] = gradient
        self.battleStats[arenaUniqueID]['palette'] = palette
        self.battleResultsBusy.release()

    def reset(self):
        self.startDate = self.getWorkDate()
        self.battles = []
        self.save()
        self.updateMessage()

    def mainLoop(self):
        while True:
            arenaUniqueID = self.queue.get()
            stat.battleResultsAvailable.wait()
            self.battleResultsBusy.acquire()
            shotBRCallback = partial(self.battleResultsCallback, arenaUniqueID)
            BigWorld.player().battleResultsCache.get(arenaUniqueID, shotBRCallback)

    def refreshColorMacros(self, values, gradient, palette):
        if values['battlesCount'] == 0:
            for key in values.keys():
                gradient[key] = '#FFFFFF'
                palette[key] = '#FFFFFF'
            return
        for key in values.keys():
            if self.config.get('gradient', {}).has_key(key):
                colors = self.config.get('gradient', {})[key]
                if values[key] <= colors[0]['value']:
                    gradient[key] = colors[0]['color']
                elif values[key] >= colors[-1]['value']:
                    gradient[key] = colors[-1]['color']
                else:
                    sVal = colors[0]['value']
                    eVal = colors[1]['value']
                    i = 1
                    while eVal < values[key]:
                        sVal = colors[i]['value']
                        i += 1
                        eVal = colors[i]['value']
                    val = float(values[key] - sVal)/(eVal - sVal)
                    gradient[key] = gradColor(colors[i - 1]['color'], colors[i]['color'], val)
            else:
                gradient[key] = '#FFFFFF'
            if self.config.get('palette', {}).has_key(key):
                colors = self.config.get('palette', {})[key]
                palette[key] = colors[-1]['color']
                for item in reversed(colors):
                    if values[key] <= item['value']:
                        palette[key] = item['color']
                    else:
                        break
            else:
                palette[key] = '#FFFFFF'

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

    def calcWN8(self, battles, values, gradient, palette):
        values['battlesCount'] = len(battles)
        totalTier = 0
        totalBattleTier = 0
        valuesKeys = ['winsCount', 'totalDmg', 'totalFrag', 'totalSpot', 'totalDef', 'totalCap', \
            'totalShots', 'totalHits', 'totalPierced', 'totalAssist', 'totalXP', 'totalOriginXP', \
            'totalAutoRepair', 'totalAutoEquip', 'totalAutoLoad', 'credits', 'gold']
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
            values['totalCap'] += battle['cap']
            values['totalShots'] += battle['shots']
            values['totalHits'] += battle['hits']
            values['totalPierced'] += battle['pierced']
            values['totalAssist'] += battle['assist']
            values['totalXP'] += battle['xp']
            values['totalOriginXP'] += battle['originalXP']
            values['totalAutoRepair'] += battle['autoRepair']
            values['totalAutoEquip'] += battle['autoEquip']
            values['totalAutoLoad'] += battle['autoLoad']
            values['credits'] += battle['credits']
            values['gold'] += battle['gold']
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
            values['avgCap'] = float(values['totalCap'])/values['battlesCount']
            values['avgHitsRate'] = float(values['totalHits'])/max(1, values['totalShots'])*100
            values['avgEffHitsRate'] = float(values['totalPierced'])/max(1, values['totalHits'])*100
            values['avgAssist'] = int(values['totalAssist'])/values['battlesCount']
            values['avgXP'] = int(values['totalXP']/values['battlesCount'])
            values['avgOriginalXP'] = int(values['totalOriginXP']/values['battlesCount'])
            values['avgCredits'] = int(values['credits']/values['battlesCount'])
            values['avgTier'] = round(float(totalTier)/values['battlesCount'], 1)
            values['avgBattleTier'] = round(float(totalBattleTier)/values['battlesCount'], 1)
            for key in expKeys:
                values[key] = expValues['total_' + key]/values['battlesCount']
            values['WN6'] = max(0, int((1240 - 1040/(min(values['avgTier'], 6))**0.164)*values['avgFrag'] + \
                values['avgDamage']*530/(184*math.exp(0.24*values['avgTier']) + 130) + \
                values['avgSpot']*125 + min(values['avgDef'], 2.2)*100 + \
                ((185/(0.17 + math.exp((values['avgWinRate'] - 35)* -0.134))) - 500)*0.45 + \
                (6-min(values['avgTier'], 6))*-60))
            values['XWN6'] = 100 if values['WN6'] > 2300 \
                else int(max(min(values['WN6']*(values['WN6']*(values['WN6']*(values['WN6']*\
                (values['WN6']*(0.00000000000000000466*values['WN6'] - 0.000000000000032413) + \
                0.00000000007524) - 0.00000006516) + 0.00001307) + 0.05153) - 3.9, 100), 0))
            values['EFF'] = max(0, int(values['avgDamage']*(10/(values['avgTier'] + 2)) *\
                (0.23 + 2*values['avgTier']/100) + values['avgFrag'] * 250 + \
                values['avgSpot'] * 150 + math.log(values['avgCap'] + 1, 1.732) * 150 + \
                values['avgDef'] * 150))
            values['XEFF'] = 0 if values['EFF'] < 350 \
                else int(max(min(values['EFF']*(values['EFF']*(values['EFF']*(values['EFF']*\
                (values['EFF']*(0.00000000000000003388*values['EFF'] - 0.0000000000002469) + \
                0.00000000069335) - 0.00000095342) + 0.0006656) -0.1485) - 0.85, 100), 0))
        else:
            for key in ['avgWinRate', 'avgDamage', 'avgFrag', 'avgSpot', 'avgDef', 'avgCap', 'avgHitsRate', \
                'avgEffHitsRate', 'avgAssist', 'avgXP', 'avgOriginalXP', 'avgCredits', 'avgTier', 'avgBattleTier',\
                'WN6', 'XWN6', 'EFF', 'XEFF']:
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
        values['avgDamage'] = int(values['avgDamage'])
        self.refreshColorMacros(values, gradient, palette)

    def num2Str(self, val):
        sVal = format(val, ',.2f') if type(val) is float \
            else format(val, ',d')
        sVal = sVal.replace(',', ' ')
        return sVal

    def updateMessage(self):
        if not self.configIsValid:
            self.message = 'stat_config.json is not valid'
            return
        self.calcWN8(self.battles, self.values, self.gradient, self.palette)
        msg = '\n'.join(self.config.get('template',''))
        for key in self.values.keys():
            msg = msg.replace('{{%s}}' % key, self.num2Str(self.values[key]))
            msg = msg.replace('{{g:%s}}' % key, self.gradient[key])
            msg = msg.replace('{{c:%s}}' % key, self.palette[key])
        self.message = msg

    def replaceBattleResultMessage(self, message, arenaUniqueID):
        battleStatText = '\n'.join(self.config.get('battleStatText',''))
        values = self.battleStats[arenaUniqueID]['values']
        gradient = self.battleStats[arenaUniqueID]['gradient']
        palette = self.battleStats[arenaUniqueID]['palette']
        for key in values.keys():
            battleStatText = battleStatText.replace('{{%s}}' % key, self.num2Str(values[key]))
            battleStatText = battleStatText.replace('{{g:%s}}' % key, gradient[key])
            battleStatText = battleStatText.replace('{{c:%s}}' % key, palette[key])
        return message + '\n<font color=\'#929290\'>' + battleStatText + '</font>'

    def filterNotificationList(self, item):
        message = item['message'].get('message', '')
        if type(message) == str:
            msg = unicode(message, 'utf-8')
            for pattern in self.config.get('hideMessagePatterns', []):
                if re.search(pattern, msg, re.I):
                    return False
        return True

    def expandStatNotificationList(self, item):
        arenaUniqueID = int(item['message'].get('savedID', -1))
        message = item['message'].get('message', '')
        if arenaUniqueID > 0 and self.battleStats.has_key(arenaUniqueID) and type(message) == str:
            message = self.replaceBattleResultMessage(message, arenaUniqueID)
            item['message']['message'] = message
        return item

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
    if stat.config.get('onlineReloadConfig', False):
        stat.readConfig()
        stat.updateMessage()
        stat.config['onlineReloadConfig'] = True
    old_nlv_populate(self)
    self.as_appendMessageS(stat.createMessage())

old_nlv_onClickAction = NotificationListView.onClickAction

def new_onClickAction(self, typeID, entityID, action):
    if action == 'wotstatReset':
        stat.reset()
    else:
        old_nlv_onClickAction(self, typeID, entityID, action)

NotificationListView.onClickAction = new_onClickAction

NotificationListView._populate = new_nlv_populate

def new_nlv_setNotificationList(self):
    formedList = map(lambda item: item.getListVO(), self._model.collection.getListIterator())
    if len(stat.config.get('hideMessagePatterns', [])):
        formedList = filter(stat.filterNotificationList, formedList)
    if stat.config.get('showStatForBattle', True):
        formedList = map(stat.expandStatNotificationList, formedList)
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
