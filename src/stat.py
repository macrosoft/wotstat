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
from helpers import i18n
from notification.NotificationListView import NotificationListView
from notification.NotificationPopUpViewer import NotificationPopUpViewer
from messenger import MessengerEntry
from messenger.formatters.service_channel import BattleResultsFormatter
from Queue import Queue
from debug_utils import *

GENERAL = 0
BY_TANK = 1

#BattleResultsCache.clean = lambda *args: None

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
        self.page = GENERAL
        self.cacheVersion = 6
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
        self.battleStatPatterns = []
        self.messageGeneral = ''
        self.messageByTank = ''
        self.playerName = ''
        self.bgIcon = ''
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
                self.configFilePath = path + 'wotstat/config.json'
                self.statCacheFilePath = path + 'wotstat/cache.json'
                expectedValuesPath = path + 'wotstat/expected_tank_values.json'
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
                    not self.config.get('dailyAutoReset', True)) and \
                    not self.config.get('clientReloadReset', False):
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
                self.battleStatPatterns = []
                for pattern in self.config.get('battleStatPatterns',[]):
                    try:
                        condition = pattern.get('if', 'True')
                        condition = re.sub('{{(\w+)}}', 'values[\'\\1\']', condition)
                    except:
                        print "[wotstat] Invalid condition " + pattern.get('if','')
                        continue
                    try:
                        compiled = re.compile(pattern.get('pattern',''))
                        self.battleStatPatterns.append({
                            'condition': condition,
                            'pattern': compiled,
                            'repl': pattern.get('repl','')
                        })
                    except:
                        print "[wotstat] Invalid pattern " + pattern.get('pattern','')
                        continue
                self.configIsValid = True
            except:
                print '[wotstat] load stat_config.json has failed'
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
        messages = {
                GENERAL: self.messageGeneral, 
                BY_TANK: self.messageByTank
            }
        msg = messages[self.page]
        message = {
            'typeID': 1,
            'message': {
                'bgIcon': self.bgIcon,
                'defaultIcon': '',
                'savedData': 0,
                'timestamp': -1,
                'filters': [],
                'buttonsLayout': [],
                'message': msg,
                'type': 'black',
                'icon': self.config.get('icon', "../maps/icons/library/BattleResultIcon-1.png"),
            },
            'entityID': 99999,
            'auxData': ['GameGreeting']
        }
        if len(self.battles) and self.config.get('showStatByTank', True):
            buttonNames = {
                GENERAL: self.config.get('textGeneralPageButton', 'By tank'), 
                BY_TANK: self.config.get('textByTankPageButton', 'General')
            }
            message['message']['buttonsLayout'].append({
                'action': 'wotstatSwitchPage',
                'type': 'submit',
                'label': buttonNames[self.page]
            })
        if self.config.get('showResetButton', False):
            message['message']['buttonsLayout'].append({
                'action': 'wotstatReset',
                'type': 'submit',
                'label': self.config.get('textResetButton', 'Reset')
            })
        return message

    def battleResultsCallback(self, arenaUniqueID, responseCode, value = None, revision = 0):
        if responseCode == AccountCommands.RES_NON_PLAYER or responseCode == AccountCommands.RES_COOLDOWN:
            BigWorld.callback(1.0, lambda: self.queue.put(arenaUniqueID))
            self.battleResultsBusy.release()
            return
        if responseCode < 0:
            self.battleResultsBusy.release()
            return
        arenaTypeID = value['common']['arenaTypeID']
        arenaType = ArenaType.g_cache[arenaTypeID]
        personal = value['personal'].itervalues().next()
        vehicleCompDesc = personal['typeCompDescr']
        vt = vehiclesWG.getVehicleType(vehicleCompDesc)
        result = 1 if int(personal['team']) == int(value['common']['winnerTeam'])\
            else (0 if not int(value['common']['winnerTeam']) else -1)
        place = 1
        arenaUniqueID = value['arenaUniqueID']
        squadsTier = {}
        vehicles = value['vehicles']
        for vehicle in vehicles.values():
            pTypeCompDescr = vehicle[0]['typeCompDescr']
            if pTypeCompDescr is not None:
                pvt = vehiclesWG.getVehicleType(pTypeCompDescr)
                tier = pvt.level
                if set(vehiclesWG.VEHICLE_CLASS_TAGS.intersection(pvt.tags)).pop() == 'lightTank' and tier > 5:
                    tier += 1
                squadId = value['players'][vehicle[0]['accountDBID']]['prebattleID']
                squadsTier[squadId] = max(squadsTier.get(squadId, 0), tier)
            if personal['team'] == vehicle[0]['team'] and \
                personal['originalXP'] < vehicle[0]['xp']:
                place += 1
        battleTier = 11 if max(squadsTier.values()) == 10 and min(squadsTier.values()) == 9 \
            else max(squadsTier.values())
        proceeds = personal['credits'] - personal['autoRepairCost'] -\
                   personal['autoEquipCost'][0] - personal['autoLoadCost'][0]
        tmenXP = personal['tmenXP']
        if 'premium' in vt.tags:
            tmenXP = int(1.5*tmenXP)
        battle = {
            'idNum': vehicleCompDesc,
            'map': arenaType.geometryName,
            'vehicle': vt.name.replace(':', '-'),
            'tier': vt.level,
            'result': result,
            'damage': personal['damageDealt'],
            'frag': personal['kills'],
            'spot': personal['spotted'],
            'def': personal['droppedCapturePoints'],
            'cap': personal['capturePoints'],
            'shots': personal['shots'],
            'hits': personal['directHits'],
            'pierced': personal['piercings'],
            'xp': personal['xp'],
            'originalXP': personal['originalXP'],
            'freeXP': personal['freeXP'],
            'place': place,
            'credits': proceeds,
            'gold': personal['gold'] - personal['autoEquipCost'][1] - personal['autoLoadCost'][1],
            'battleTier': battleTier,
            'assist': personal['damageAssistedRadio'] + personal['damageAssistedTrack'],
            'assistRadio': personal['damageAssistedRadio'],
            'assistTrack': personal['damageAssistedTrack']
        }
        extended = {
            'vehicle': battle['vehicle'],
            'map': battle['map'],
            'result': result,
            'autoRepair': personal['autoRepairCost'],
            'autoEquip': personal['autoEquipCost'][0],
            'autoLoad': personal['autoLoadCost'][0],
            'tmenXP': tmenXP
        }
        if self.config.get('dailyAutoReset', True) and self.startDate != stat.getWorkDate():
            self.reset()
        if value['common']['guiType'] not in self.config.get('ignoreBattleType', []):
            self.battles.append(battle)
            self.save()
            self.updateMessage()
        (battleStat, gradient, palette) = self.calcWN8([battle])
        (extGradient, extPalette) = self.refreshColorMacros(extended)
        gradient.update(extGradient)
        palette.update(extPalette)
        self.battleStats[arenaUniqueID] = {}
        self.battleStats[arenaUniqueID]['values'] = battleStat
        self.battleStats[arenaUniqueID]['extendedValues'] = extended
        self.battleStats[arenaUniqueID]['gradient'] = gradient
        self.battleStats[arenaUniqueID]['palette'] = palette
        self.battleResultsBusy.release()

    def reset(self):
        self.page = GENERAL
        self.startDate = self.getWorkDate()
        self.battles = []
        self.save()
        self.updateMessage()

    def mainLoop(self):
        while True:
            arenaUniqueID = self.queue.get()
            self.battleResultsAvailable.wait()
            self.battleResultsBusy.acquire()
            BigWorld.player().battleResultsCache.get(arenaUniqueID,\
                lambda resID, value: self.battleResultsCallback(arenaUniqueID, resID, value, None))

    def refreshColorMacros(self, values):
        gradient = {}
        palette = {}
        if values.get('battlesCount', 1) == 0:
            for key in values.keys():
                gradient[key] = '#FFFFFF'
                palette[key] = '#FFFFFF'
            return (gradient, palette)
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
                    if values[key] < item['value']:
                        palette[key] = item['color']
                    else:
                        break
            else:
                palette[key] = '#FFFFFF'
        return (gradient, palette)

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
            try:
                vt = vehiclesWG.getVehicleType(idNum)
            except:
                continue
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

    def calcWN8(self, battles):
        values = {}
        values['battlesCount'] = len(battles)
        totalTier = 0
        totalPlace = 0
        places = []
        totalBattleTier = 0
        valuesKeys = ['winsCount', 'defeatsCount', 'drawsCount', 'totalDmg', 'totalFrag', 'totalSpot',\
            'totalDef', 'totalCap', 'totalShots', 'totalHits', 'totalPierced', 'totalAssist',\
            'totalXP', 'totalOriginXP', 'totalFreeXP', 'credits', 'gold',\
            'totalAssistRadio', 'totalAssistTrack']
        for key in valuesKeys:
            values[key] = 0
        expKeys = ['expDamage', 'expFrag', 'expSpot', 'expDef', 'expWinRate']
        expValues = {}
        for key in expKeys:
            expValues['total_' + key] = 0.0
        resCounters = {-1: 'defeatsCount', 0: 'drawsCount', 1: 'winsCount'}
        for battle in battles:
            values[resCounters[battle['result']]] += 1
            values['totalDmg'] += battle['damage']
            values['totalFrag'] += battle['frag']
            values['totalSpot'] += battle['spot']
            values['totalDef'] += battle['def']
            values['totalCap'] += battle['cap']
            values['totalShots'] += battle['shots']
            values['totalHits'] += battle['hits']
            values['totalPierced'] += battle['pierced']
            values['totalAssist'] += battle['assist']
            values['totalAssistRadio'] += battle['assistRadio']
            values['totalAssistTrack'] += battle['assistTrack']
            values['totalXP'] += battle['xp']
            values['totalOriginXP'] += battle['originalXP']
            values['totalFreeXP'] += battle['freeXP']
            values['credits'] += battle['credits']
            values['gold'] += battle['gold']
            totalTier += battle['tier']
            totalBattleTier += battle['battleTier']
            totalPlace += battle['place']
            places.append(battle['place'])
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
            values['avgAssistRadio'] = int(values['totalAssistRadio'])/values['battlesCount']
            values['avgAssistTrack'] = int(values['totalAssistTrack'])/values['battlesCount']
            values['avgXP'] = int(values['totalXP']/values['battlesCount'])
            values['avgOriginalXP'] = int(values['totalOriginXP']/values['battlesCount'])
            values['avgPremXP'] = int(1.5*values['avgOriginalXP'])
            values['avgCredits'] = int(values['credits']/values['battlesCount'])
            values['avgTier'] = float(totalTier)/values['battlesCount']
            values['avgBattleTier'] = float(totalBattleTier)/values['battlesCount']
            places = sorted(places)
            length = len(places)
            values['medPlace'] = (places[length/2] +places[length/2 - 1])/2.0  if not length % 2\
                else float(places[length/2])
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
            values['BR'] = max(0, int(values['avgDamage']*(0.2 + 1.5/values['avgTier']) + \
                values['avgFrag'] * (350 - values['avgTier'] * 20) + \
                ((values['avgAssistRadio']/2)*(0.2 + 1.5/values['avgTier'])) + \
                ((values['avgAssistTrack']/2)*(0.2 + 1.5/values['avgTier'])) + \
                values['avgSpot'] * 200 + values['avgCap'] * 15 + values['avgDef'] * 15 ))
            values['WN7'] = max(0, int((1240 - 1040/(min(values['avgTier'], 6))**0.164)*values['avgFrag'] + \
                values['avgDamage']*530/(184*math.exp(0.24*values['avgTier']) + 130) + \
                values['avgSpot']*125*(min(values['avgTier'], 3))/3 + min(values['avgDef'], 2.2)*100 + \
                ((185/(0.17 + math.exp((values['avgWinRate'] - 35)* -0.134))) - 500)*0.45 - \
                ((5-min(values['avgTier'], 5))*125) / \
                (1+math.exp((values['avgTier'] - (values['battlesCount']/220)**(3/values['avgTier']))*1.5)) ))                
        else:
            for key in ['avgWinRate', 'avgDamage', 'avgFrag', 'avgSpot', 'avgDef', 'avgCap', 'avgHitsRate', \
                'avgEffHitsRate', 'avgAssist', 'avgXP', 'avgOriginalXP', 'avgPremXP', 'avgCredits', 'avgTier', \
                'avgBattleTier', 'medPlace', 'WN6', 'XWN6', 'EFF', 'XEFF', 'BR', 'WN7']:
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
        values['XWN8'] = 100 if values['WN8'] > 3650 \
            else int(max(min(values['WN8']*(values['3800']*(values['WN8']*(values['WN8']*(values['WN8']*\
            (-0.00000000000000000009762*values['WN8'] + 0.0000000000000016221) - 0.00000000001007) +\
            0.000000027916) - 0.000036982) + 0.05577) - 1.3, 100), 0))
        values['WN8'] = int(values['WN8'])
        values['avgDamage'] = int(values['avgDamage'])
        (gradient, palette) = self.refreshColorMacros(values)
        return (values, gradient, palette)
        
    def applyMacros(self, val, prec = 2):
        if type(val) == str:
            return val
        if prec <= 0:
            return format(int(round(val)), ',d')
        sVal = format(val, ',.%sf' % prec) \
            if type(val) is float else format(val, ',d')
        sVal = sVal.replace(',', ' ')
        return sVal

    def formatString(self, text, values, gradient, palette):
        for key in values.keys():
            text = text.replace('{{%s}}' % key, self.applyMacros(values[key]))
            text = text.replace('{{%s:d}}' % key, self.applyMacros(values[key], 0))
            text = text.replace('{{%s:1f}}' % key, self.applyMacros(values[key], 1))
            text = text.replace('{{g:%s}}' % key, gradient[key])
            text = text.replace('{{c:%s}}' % key, palette[key])
        return text

    def updateMessage(self):
        if not self.configIsValid:
            self.message = 'stat_config.json is not valid'
            return
        (self.values, self.gradient, self.palette) = self.calcWN8(self.battles)
        bg = self.config.get('bgIcon', '')
        self.bgIcon = self.formatString(bg, self.values, self.gradient, self.palette)
        msg = '\n'.join(self.config.get('template',''))
        msg = self.formatString(msg, self.values, self.gradient, self.palette)
        self.messageGeneral = msg
        msg = self.config.get('byTankTitle','')
        tankStat = {}
        for battle in self.battles:
            idNum = battle['idNum']
            if tankStat.has_key(idNum):
                tankStat[idNum].append(battle)
            else:
                tankStat[idNum] = [battle]
        for idNum in sorted(tankStat.keys(), key = lambda idNum: len(tankStat[idNum]), reverse = True):
            row = self.config.get('byTankRow','')
            (values, gradient, palette) = self.calcWN8(tankStat[idNum])
            vt = vehiclesWG.getVehicleType(idNum)
            row = row.replace('{{vehicle}}', vt.shortUserString)
            name = vt.name.replace(':', '-')
            row = row.replace('{{vehicle-name}}', name)
            row = self.formatString(row, values, gradient, palette)
            msg += '\n' + row 
        self.messageByTank = msg

    def replaceBattleResultMessage(self, message, arenaUniqueID):
        message = unicode(message, 'utf-8')
        if self.config.get('debugBattleResultMessage', False):
            LOG_NOTE(message)
        basicValues = self.battleStats[arenaUniqueID]['values']
        extendedValues = self.battleStats[arenaUniqueID]['extendedValues']
        values = basicValues
        values.update(extendedValues)
        for pattern in self.battleStatPatterns:
            try:
                if not eval(pattern.get('condition')):
                    continue
            except:
                print "[wotstat] Invalid calculation condition " + pattern.get('condition')
                continue
            message = re.sub(pattern.get('pattern',''), pattern.get('repl',''), message)
        battleStatText = '\n'.join(self.config.get('battleStatText',''))
        gradient = self.battleStats[arenaUniqueID]['gradient']
        palette = self.battleStats[arenaUniqueID]['palette']
        message = message + '\n<font color=\'#929290\'>' + battleStatText + '</font>'
        message = self.formatString(message, values, gradient, palette)
        return message

    def filterNotificationList(self, item):
        message = item['message'].get('message', '')
        msg = unicode(message, 'utf-8') if isinstance(message, str) \
            else message if isinstance(message, unicode) else None
        if msg:
            for pattern in self.config.get('hideMessagePatterns', []):
                if re.search(pattern, msg, re.I):
                    return False
        return True

    def expandStatNotificationList(self, item):
        savedData = item['message'].get('savedData', -1)
        arenaUniqueID = -1
        if isinstance(savedData, long):
            arenaUniqueID = int(savedData)
        elif isinstance(savedData, tuple):
            arenaUniqueID = int(savedData[0])
        message = item['message'].get('message', '')
        if arenaUniqueID > 0 and self.battleStats.has_key(arenaUniqueID) and type(message) == str:
            message = self.replaceBattleResultMessage(message, arenaUniqueID)
            item['message']['message'] = message
            if self.config.get('overwriteBattleResultBgIcon', False):
                result = self.battleStats[arenaUniqueID]['extendedValues']['result']
                bgIconKeys = {-1: 'bgIconDefeat', 0: 'bgIconDraw', 1: 'bgIconWin'}
                bgIconKey = bgIconKeys[result]
                bgIcon = self.config.get(bgIconKey, item['message']['bgIcon'])
                item['message']['bgIcon'] = bgIcon
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

NotificationListView._populate = new_nlv_populate

old_nlv_onClickAction = NotificationListView.onClickAction

def new_onClickAction(self, typeID, entityID, action):
    if action == 'wotstatReset':
        stat.reset()
    elif action == 'wotstatSwitchPage':
        stat.page = 1 - stat.page
    else:
        old_nlv_onClickAction(self, typeID, entityID, action)

NotificationListView.onClickAction = new_onClickAction

def new_nlv_setNotificationList(self):
    formedList = map(lambda item: item.getListVO(), self._model.collection.getListIterator())
    if len(stat.config.get('hideMessagePatterns', [])):
        formedList = filter(stat.filterNotificationList, formedList)
    if stat.config.get('showStatForBattle', True):
        formedList = map(stat.expandStatNotificationList, formedList)
    self.as_setMessagesListS(formedList)

NotificationListView._NotificationListView__setNotificationList = new_nlv_setNotificationList

old_npuv_sendMessageForDisplay = NotificationPopUpViewer._NotificationPopUpViewer__sendMessageForDisplay

def new_npuv_sendMessageForDisplay(self, notification):
    if stat.config.get('showPopUp', True):
        old_npuv_sendMessageForDisplay(self, notification)

NotificationPopUpViewer._NotificationPopUpViewer__sendMessageForDisplay = new_npuv_sendMessageForDisplay

old_brf_format = BattleResultsFormatter.format

def new_brf_format(self, message, *args):
    result = old_brf_format(self, message, *args)
    arenaUniqueID = message.data.get('arenaUniqueID', 0)
    stat.queue.put(arenaUniqueID)
    if stat.config.get('enableBattleEndedMessage', True) and hasattr(BigWorld.player(), 'arena'):
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
            playerVehicles = message.data['playerVehicles'].itervalues().next()
            vehicleCompDesc = playerVehicles['vehTypeCompDescr']
            vt = vehiclesWG.getVehicleType(vehicleCompDesc)
            battleEndedMessage = battleEndedMessage.replace('{{vehicle}}', vt.userString)
            name = vt.name.replace(':', '-')
            battleEndedMessage = battleEndedMessage.replace('{{vehicle-name}}', name)
            arenaTypeID = message.data.get('arenaTypeID', 0)
            arenaType = ArenaType.g_cache[arenaTypeID]
            arenaName = i18n.makeString(arenaType.name)
            xp = message.data.get('xp', 0)
            credits = message.data.get('credits', 0)
            battleEndedMessage = battleEndedMessage.replace('{{map}}', arenaName)
            battleEndedMessage = battleEndedMessage.replace('{{map-name}}', arenaType.geometryName)
            battleEndedMessage = battleEndedMessage.replace('{{xp}}', str(xp))
            battleEndedMessage = battleEndedMessage.replace('{{credits}}', str(credits))
            MessengerEntry.g_instance.gui.addClientMessage(battleEndedMessage)
    return result

BattleResultsFormatter.format = new_brf_format

stat = SessionStatistic()
