# -*- coding: utf-8 -*-
import sys
import time
import optparse
import datetime
from utils import logger

from activity import *

from conf import sysconfig
from apscheduler.schedulers.blocking import BlockingScheduler

reload(sys)
sys.setdefaultencoding('utf8')

def generate_dates(start_date, end_date):
    td = datetime.timedelta(hours=24)
    current_date = start_date
    date_list = []
    while current_date <= end_date:
        date_list.append(current_date)
        current_date += td
    return date_list

def get_date_range():
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today - datetime.timedelta(days=1)

    return start_date, end_date

def timer_job():
    start_date, end_date = get_date_range()
    date_list = generate_dates(start_date, end_date)
    logger.info('calculating fingerprints\' credit on %s start!' % start_date)
    try:
        userScore = UserActivity(date_list)
        userScore.run()
    except Exception as e:
        logger.error('calculating fingerprints\' credit on %s encountered error: %s' % (start_date, str(e)))
    logger.info('calculating fingerprints\' credit on %s end!' % start_date)

if __name__ == '__main__':
    parser = optparse.OptionParser()
    parser.add_option('-s', '--start', action='store', dest="start_date",
        help="calculate user's activity from this day, for example: 2018-05-01")

    options, args = parser.parse_args()

    today = datetime.date.today()
    # start time
    start_date = options.start_date
    if start_date is not None:
        dates = start_date.split('-')
        start_date = datetime.date(int(dates[0]), int(dates[1]), int(dates[2]))
    else:
        start_date = today - datetime.timedelta(days=1)

    # end time
    end_date = today - datetime.timedelta(days=1)

    date_list = generate_dates(start_date, end_date)

    userScore = UserActivity(date_list)
    try:
        userScore.run()
    except Exception as e:
        logger.error('encountered an error when calculating credit firt time, err: %s' % str(e))
        sys.exit()

    sched = BlockingScheduler()
    # start program in am is best.
    sched.add_job(timer_job, 'cron', hour=5)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
