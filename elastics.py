# coding:utf-8
import json
import socket
from utils import logger

from conf import sysconfig

from multiprocessing import Pool, Manager
from elasticsearch_dsl import Search
from elasticsearch import Elasticsearch

# for elasticsearch sliced scroll
SLICES = sysconfig.ES_THREADS


# Define config
HOST = sysconfig.ES_HOST
PORT = sysconfig.ES_PORT
TIMEOUT = 1000
DOC_TYPE = "ngx_error_log"

# Init Elasticsearch instance

def getIP(errorMsg):
   splits = errorMsg.split(',') 
   if len(splits) > 3:
       clientIP = splits[2]
       if clientIP is not None:
           info = clientIP.split(': ')
           return info[1]

def dump_slice(args):
    index = args[0]
    slice_no = args[1]
    result = []

    try:
        client = Elasticsearch([{'host': HOST, 'port': PORT}], timeout=TIMEOUT)

        s = Search(using=client, index=index, doc_type=DOC_TYPE).query('wildcard', error_msg='*kfirewall*')
        s = s.extra(slice={"id":slice_no, "max":SLICES})
        for resp in s.params(scroll='4m').scan():
            host = resp['host']
            error_msg = resp['error_msg']
            timestamp = resp['Timestamp']
            ip = getIP(error_msg)
            if ip is not None:
                try:
                    socket.inet_aton(ip)
                    result.append((ip, host, timestamp))
                except socket.error:
                    continue
        return result
    except Exception, e:
        logger.info('search elasticsearch failed, err:%s' % str(e))

def queryfromes(index):
    # Check index exists

    result = {}
    args = []
    for slice_no in range(SLICES):
        args.append((index, slice_no, result))

    pool = Pool(SLICES)
    data = pool.map(dump_slice, args)
    pool.close()
    pool.join()
    for d in data:
        for ipmeta in d:
            ip = ipmeta[0]
            host = ipmeta[1]
            timestamp = ipmeta[2]
            if ip not in result:
                result[ip] = {'count':0, 'host':host, 'timestamp':timestamp}
            result[ip]['count'] += 1
    return result
