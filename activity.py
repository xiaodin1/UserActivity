# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import json
import redis
import math
import pickle
import pymysql
import datetime

from pathlib import Path
from utils import logger

from user import *
from elastics import queryfromes
from conf import sysconfig

AK_REDIS_HOST = sysconfig.AK_REDIS_HOST
AK_REDIS_PORT = sysconfig.AK_REDIS_PORT
AK_REDIS_PASSWD = sysconfig.AK_REDIS_PASSWD
AK_REDIS_DB = sysconfig.AK_REDIS_DB

FP_REDIS_HOST = sysconfig.FP_REDIS_HOST
FP_REDIS_PORT = sysconfig.FP_REDIS_PORT
FP_REDIS_PASSWD = sysconfig.FP_REDIS_PASSWD
FP_REDIS_DB = sysconfig.FP_REDIS_DB

DAT_PATH = sysconfig.DAT_PATH

# Connect to mysql
connection = pymysql.connect(host='127.0.0.1',
                       user='root',
                       passwd='dbadmin',
                       db='usercredit',
                       charset='utf8mb4',
                       cursorclass=pymysql.cursors.DictCursor)

def writeUserInfoToMySQL(fp, level, accesskey, score, timestamp):
    with connection.cursor() as cursor:
        # Create a new record
        sql = """
            INSERT INTO activity
                (fp, level, accesskey, score, timestamp)
            VALUES
                (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                level = VALUES(level),
                timestamp = VALUES(timestamp),
                score = VALUES(score);
            """
        cursor.execute(sql, (fp, level, accesskey, score, timestamp))

    connection.commit()

try:
    fingerprint_pool = redis.ConnectionPool(host=FP_REDIS_HOST, port=FP_REDIS_PORT, db=FP_REDIS_DB, password=FP_REDIS_PASSWD)
    fingerprint_red_cli = redis.Redis(connection_pool=fingerprint_pool)
    portnum_red_cli = redis.Redis(host=AK_REDIS_HOST, port=AK_REDIS_PORT, db = AK_REDIS_DB, password=AK_REDIS_PASSWD)
except Exception, e:
    logger.error('connect redis failed, err msg:%s' % str(e))
    sys.exit(1)

def getLastestDatFile(path):
    '''get the lastest stat file'''
    f_list = os.listdir(path)
    for filename in f_list:
        if os.path.splitext(filename)[1] == '.dat':
            lastest = os.path.join(path, filename)
            return lastest

def delHistoryDateFile(path):
    '''remove history data file'''
    f_list = os.listdir(path)
    for filename in f_list:
        if os.path.splitext(filename)[1] == '.dat':
            dst = os.path.join(path, filename)
            os.remove(dst)

def write_activity_score_to_redies(score_dict):
    for accesskey, user in score_dict.items():
        pipe = fingerprint_red_cli.pipeline(transaction=True)
        for fingerprint, user in user.items():
            key = 'fp_%s' % fingerprint
            score = user.score
            timestamp = user.timestamp

            pipe.hset(key, 'score_activity', score)
            
            level = 'good'
            if score <= 15:
                level = 'gaofang'
            elif score <= 55:
                level = 'personal'

            pipe.hset(key, 'level', level)
            writeUserInfoToMySQL(fingerprint, level, accesskey, float(score), timestamp)
        pipe.execute()

def write_activity_score(score_dict, date):
    dirname = os.path.dirname(os.path.realpath(__file__))
    filename = dirname +'/scores.txt'
    score_file = open(filename, 'a+')
    for accesskey, score in score_dict.items():
        for fingerprint, user_score in score.items():
            record = '%s    %s    %s    %s\n' %(date, accesskey, fingerprint, user_score)
            score_file.write(record)

    score_file.close()

def accesskey_port_num():
    result = {}
    keys = []
    for key in portnum_red_cli.scan_iter():
        keys.append(key)
    if keys is not None:
        for accesskey in keys:
            json_data = portnum_red_cli.get(accesskey)
            decoded = json.loads(json_data)
            result[accesskey] = len(decoded['tcp'])
    return result

class UserActivity():
    def __init__(self, date_list):
        self.date_list = date_list

        self.users = {}
        historydata = getLastestDatFile(DAT_PATH)
        if historydata is not None and  Path(historydata).is_file():
            history = open(historydata, 'rb')
            history_stats = pickle.load(history)
            if history_stats is not None:
                self.users = history_stats

        port = accesskey_port_num()
        if port is not None:
            self.portNum = port

    def UpdateAcitivity(self, logMsgList):
        for i, record in enumerate(logMsgList):
            if 'fingerprint' not in record:
                return

            fingerprint = record['fingerprint']
            accesskey = record['accesskey']
            if accesskey in self.users:
                if fingerprint in self.users[accesskey]:
                    blacktime = fingerprint_red_cli.hget(fingerprint, 'blacktime')
                    if blacktime is not None:
                        orig = datetime.datetime.fromtimestamp(int(blacktime))
                        limit  = orig + datetime.timedelta(days=3)
                        if datetime.datetime.now() < limit:
                            continue
                    user = self.users[accesskey][fingerprint]
                else:
                    user = User()
                if accesskey in self.portNum:
                    user.target_port_total = self.portNum[accesskey]
                user.DailyStats(record)
                self.users[accesskey][fingerprint] = user
            else:
                self.users[accesskey] = {}
                user = User()
                user.DailyStats(record)
                self.users[accesskey][fingerprint] = user

    def Run(self):
        self.scores = {}
        for day in self.date_list:
            logger.info('beginning analysis %s tjkd app log' % day)
            start = time.time()
            result_list = queryfromes("tjkd-app-{}".format(day))
            self.UpdateAcitivity(result_list)
    
            for accesskey, group in self.users.items():
                if accesskey not in self.scores:
                    self.scores[accesskey] = {}
                for fingerprint, user in group.items():
                    user.UpdateStats() 
                    user.Score()
                    user.ClearDailyStats()
                    self.scores[accesskey][fingerprint] = user
            
            write_activity_score_to_redies(self.scores)
            done = time.time()
            elapsed = done - start
            logger.info('%s analysis end, %.2f seconds elapsed' % (day, elapsed))

        if len(self.date_list) != 0:
            delHistoryDateFile(DAT_PATH)
            filename = '%s/stats-%s.dat' % (DAT_PATH, datetime.date.today())
            outfile = open(filename, 'wb')
            pickle.dump(self.users, outfile)
            outfile.close()
