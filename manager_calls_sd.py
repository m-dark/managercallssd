#!/usr/bin/env python3.6
# pip install mysql-connector-python

import os
import re
import sys
import io
import asyncio
import panoramisk
from panoramisk import Manager
import time
from datetime import timedelta
from datetime import datetime
import mysql.connector
import subprocess
import logging
from urllib import request, parse
import ssl

date_time = datetime.strftime(datetime.now(), "%Y.%m.%d %H:%M:%S")
dir_conf = '/opt/asterisk/script/autoprovisioning/'
dir_log = '/opt/asterisk/script/log/'

log = logging.getLogger("Calls")
fh = logging.FileHandler(dir_log+'post_calls.log')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] - %(name)s: %(message)s"))
log.addHandler(fh)
log.setLevel(logging.DEBUG)
log.info('Start')

dict_DialBegin = dict()
dict_DialEnd = dict()
dict_AttendedTransfer = dict()
dict_Hangup = dict()
dict_findmefollow = dict()
dict_connect_mysql_fw = dict()
manager_host='127.0.0.1'
manager_port='5038'
manager_user='username'
manager_secret='password'
ping_delay=5
manager_connect_findmefollow=60
day = 1
yes_connect_mysql = 0
URL = ''

def push_xml(linenumber, callerid, timestart, timestop, totalsec):
	array_timestart = timestart.split('.')
	timestart = array_timestart[0]
	array_timestop = timestop.split('.')
	timestop = array_timestop[0]
	timestart = timestart.replace('-','.')
	timestop = timestop.replace('-','.')
	try:
		data = '<?xml version="1.0" encoding="utf-8"?>'+"\n"
		data += '<content Version="80903">'+"\n"
		data += '  <call commcount="3" taskcount="0">'+"\n"
		data += '    <property_simple key="direction" value="1" name="cdIncoming" />'+"\n"
		data += '    <property_simple key="linenumber" value="'+linenumber+'" />'+"\n"
		data += '    <property_simple key="callerid" value="'+callerid+'" />'+"\n"
		data += '    <property_simple key="timestart" value="'+timestart+'" />'+"\n"
		data += '    <property_simple key="timestop" value="'+timestop+'" />'+"\n"
		data += '    <property_simple key="totalsec" value="'+totalsec+'" />'+"\n"
		data += '    <property_simple key="userid" value="'+linenumber+'" />'+"\n"
		data += '  </call>'+"\n"
		data += '</content>'+"\n"
		print(data)
		post_data = parse.urlencode({'xml':data}).encode("utf-8")
		req = request.Request(URL, data=post_data)
		response = request.urlopen(url=URL, data=post_data)
		print(response.read().decode("utf-8"))
		print(response.code)
#		log.info('Отправил.')
	except Exception:
		print("Error occuried during web request!")
		print(sys.exc_info()[1])
		log.error('1_1 Информация по вызову с номера: '+callerid+'на номер: '+linenumber+' не отправлена, так как '+URL+' вернул ошибку: '+str(sys.exc_info()[1]))

def  time_connect_mysql(all_minutes):
        global dict_connect_mysql_fw
        global yes_connect_mysql
        dict_del_connect_mysql_fw = dict()
        for hash_min in dict_connect_mysql_fw:
                if hash_min <= all_minutes:
                        yes_connect_mysql = 1
                        dict_del_connect_mysql_fw[hash_min] = 0
        for hash_del in dict_del_connect_mysql_fw:
                del dict_connect_mysql_fw[hash_del]
        if yes_connect_mysql == 1:
                connect_findmefollow()

def connect_findmefollow():
	global dict_findmefollow
	dict_findmefollow = dict()
	global yes_connect_mysql
	yes_connect_mysql = 0
	db = mysql.connector.connect(host="localhost", user="root", passwd="", db="asterisk", charset='utf8')
	cursor = db.cursor()
	sql="SELECT grpnum,grplist FROM findmefollow"
	cursor.execute(sql)
	log.info('Обновил словарь номеров переадресации из таблицы FreePBX findmefollow, для подмены на внутренние номера')
	for row in cursor:
		if row[0] != row[1]:
			result=re.search(r'-', row[1])
			if result is not None:
				numpers = row[1].replace('#','')
				findmefollow_numbers = numpers.split('-')
				for number in findmefollow_numbers:
					if len(row[0]) != len(number):
						if number in dict_findmefollow:
							if row[0] in dict_findmefollow[number]:
								dict_findmefollow[number][row[0]] += 1
								log.error('Для номера '+str(number)+' настроена переадресация на номере '+ str(row[0])+' '+str(dict_findmefollow[number][row[0]])+' раз(а)')
							else:
								dict_findmefollow[number][row[0]] = 1
						else:
							dict_findmefollow[number] = dict()
							dict_findmefollow[number][row[0]] = 1
#					else:
#						здесь необходимо проверить что будет если переадресация прописана на внутренний номер другого сотрудника.
#						print(str(row[0])+'  '+str(number)+"\n")
			else:
				numper = row[1].replace('#','')
				if len(row[0]) != len(number):
					if number in dict_findmefollow:
						if row[0] in dict_findmefollow[number]:
							dict_findmefollow[number][row[0]] += 1
							log.error('Для номера '+str(number)+' настроена переадресация на номере '+ str(row[0])+' '+str(dict_findmefollow[number][row[0]])+' раз(а)')
						else:
							dict_findmefollow[number][row[0]] = 1
					else:
						dict_findmefollow[number] = dict()
						dict_findmefollow[number][row[0]] = 1
	db.commit()
	db.close()

def hangup_calls(uniqueid):
        global dict_DialBegin
        global dict_DialEnd
        global dict_Hangup
        global dict_findmefollow
        if uniqueid in dict_DialBegin:
                if dict_DialBegin[uniqueid]['ChannelStateDesc'] == 'Ring':
                        if uniqueid in dict_DialEnd:
                                if dict_DialEnd[uniqueid]['DialStatus'] == 'ANSWER':
                                        date_time_start = datetime.fromtimestamp(float(dict_DialEnd[uniqueid]['Timestamp']))
                                        date_time_stop = datetime.fromtimestamp(float(dict_Hangup[uniqueid]['Timestamp']))
                                        call_duration = round(float(dict_Hangup[uniqueid]['Timestamp']) - float(dict_DialEnd[uniqueid]['Timestamp']))
                                        if call_duration > 1:
                                                channel_param_number = ['','']
                                                result=re.match(r'SIP/', dict_Hangup[uniqueid]['Channel'])
                                                if result is not None:
####                                                        print('------------------------------------'+str(dict_Hangup[uniqueid]['Channel']))
                                                        channel_param=dict_Hangup[uniqueid]['Channel'].split('-')
                                                        channel_param_number=channel_param[0].split('/')
                                                result=re.match(r'PJSIP/\d+\-', dict_Hangup[uniqueid]['Channel'])
#                                                result=re.match(r'PJSIP/', dict_Hangup[uniqueid]['Channel'])
                                                if result is not None:
####                                                        print('------------------------------------'+str(dict_Hangup[uniqueid]['Channel']))
                                                        channel_param=dict_Hangup[uniqueid]['Channel'].split('-')
                                                        channel_param_number=channel_param[0].split('/')
                                                result=re.match(r'Local/\d+\@', dict_Hangup[uniqueid]['Channel'])
                                                if result is not None:
####                                                        print('------------------------------------'+str(dict_Hangup[uniqueid]['Channel']))
                                                        channel_param=dict_Hangup[uniqueid]['Channel'].split('@')
                                                        channel_param_number=channel_param[0].split('/')
####                                                         print('888888888888 '+channel_param_number[1]+'---'+dict_Hangup[uniqueid]['CallerIDNum']+'----'+uniqueid)

                                                han_callerIDNum = dict_Hangup[uniqueid]['CallerIDNum'].replace('#','')
                                                han_callerIDNum = han_callerIDNum.replace('FMGL-','')
                                                if channel_param_number[1] == han_callerIDNum:
                                                        if dict_DialBegin[uniqueid]['ConnectedLineNum'] in dict_findmefollow[han_callerIDNum]:
                                                                result=re.match(r'10[01]\d\d$', dict_DialBegin[uniqueid]['ConnectedLineNum'])
                                                                if result is not None:
                                                                        log.info('FW Вызов с номера: '+str(dict_Hangup[uniqueid]['ConnectedLineNum'])+' на номер: '+str(dict_DialBegin[uniqueid]['ConnectedLineNum'])+' продолжительностью разговора: '+str(call_duration)+' Начало: '+str(date_time_start)+' Завершился: '+str(date_time_stop)+' Uniqueid = '+str(dict_Hangup[uniqueid]['Uniqueid']))
#                                                                        print ('!@!@!!@!@!@!@@!'+dict_DialBegin[uniqueid]['ConnectedLineNum'])
                                                                        push_xml(str(dict_DialBegin[uniqueid]['ConnectedLineNum']), str(dict_Hangup[uniqueid]['ConnectedLineNum']), str(date_time_start), str(date_time_stop), str(call_duration))
#                                                                        print('!!55555! Вызов '+str(date_time_start)+' с номера '+str(dict_Hangup[uniqueid]['ConnectedLineNum'])+' на номер '+str(dict_DialBegin[uniqueid]['ConnectedLineNum'])+' продолжительностью разговора '+str(call_duration)+' Завершился '+str(date_time_stop)+"\n")
#                                                                        print('CallerIDNum = '+str(dict_Hangup[uniqueid]['CallerIDNum'])+' ConnectedLineNum = '+ str(dict_Hangup[uniqueid]['ConnectedLineNum']))
#                                                                        print('Uniqueid = '+str(dict_Hangup[uniqueid]['Uniqueid']))
                                                        else:
                                                                result=re.match(r'10[01]\d\d$', han_callerIDNum)
                                                                if result is not None:
                                                                        log.info('Вызов с номера: '+str(dict_Hangup[uniqueid]['ConnectedLineNum'])+' на номер: '+str(han_callerIDNum)+' продолжительностью разговора: '+str(call_duration)+' Начало: '+str(date_time_start)+' Завершился: '+str(date_time_stop)+' Uniqueid = '+str(dict_Hangup[uniqueid]['Uniqueid']))
#                                                                        print ('!@!@!!@!@!@!@@!'+dict_DialBegin[uniqueid]['ConnectedLineNum'])
                                                                        push_xml(str(han_callerIDNum), str(dict_Hangup[uniqueid]['ConnectedLineNum']), str(date_time_start), str(date_time_stop), str(call_duration))
#                                                                        print('!!77777! Вызов '+str(date_time_start)+' с номера '+str(dict_Hangup[uniqueid]['ConnectedLineNum'])+' на номер '+str(han_callerIDNum)+' продолжительностью разговора '+str(call_duration)+' Завершился '+str(date_time_stop)+"\n")
#                                                                        print('CallerIDNum = '+str(dict_Hangup[uniqueid]['CallerIDNum'])+' ConnectedLineNum = '+ str(dict_Hangup[uniqueid]['ConnectedLineNum']))
#                                                                        print('Uniqueid = '+str(dict_Hangup[uniqueid]['Uniqueid']))
#                                                else:
#                                                для отладки
#                                                        print('!!!!!!!!Вызов '+str(date_time_start)+' с номера '+str(dict_Hangup[uniqueid]['ConnectedLineNum'])+' на номер '+str(han_callerIDNum)+' продолжительностью разговора '+str(call_duration)+' Завершился '+str(date_time_stop)+"\n")
                        else:
                                log.error('Error_03: DialBegin есть, DialEnd нет! uniqueid: '+uniqueid+' DestCallerIDNum: '+dict_DialBegin[uniqueid]['DestCallerIDNum']+' DestConnectedLineNum:'+dict_DialBegin[uniqueid]['DestConnectedLineNum'])
#                else:
#                        log.error('Error_02: Hangup и DialBegin есть, но ChannelStateDesc не Reng! uniqueid: '+uniqueid+' CallerIDNum: '+dict_Hangup[uniqueid]['CallerIDNum']+' ConnectedLineNum:'+dict_Hangup[uniqueid]['ConnectedLineNum'])
#        else:
#                log.error('Error_01: Hangup есть, DialBegin нет! uniqueid: '+uniqueid+' CallerIDNum: '+dict_Hangup[uniqueid]['CallerIDNum']+' ConnectedLineNum:'+dict_Hangup[uniqueid]['ConnectedLineNum'])

        if uniqueid in dict_DialBegin:
                del dict_DialBegin[uniqueid]
        if uniqueid in dict_DialEnd:
                del dict_DialEnd[uniqueid]
        if uniqueid in dict_Hangup:
                del dict_Hangup[uniqueid]
#        print(format(dict_DialBegin)+"\n")

freepbx_pass = open(str(dir_conf)+'freepbx.pass','r',encoding="utf-8")
for line in (line.rstrip() for line in freepbx_pass.readlines()):
	result_line=re.match(r'manager_host', line)
	if result_line is not None:
		param_manager_host=line.split(' = ')
		manager_host=param_manager_host[1]
	result_line=re.match(r'manager_port', line)
	if result_line is not None:
		param_manager_port=line.split(' = ')
		manager_port=param_manager_port[1]
	result_line=re.match(r'manager_user', line)
	if result_line is not None:
		param_manager_user=line.split(' = ')
		manager_user=param_manager_user[1]
	result_line=re.match(r'manager_secret', line)
	if result_line is not None:
		param_manager_secret=line.split(' = ')
		manager_secret=param_manager_secret[1]
	result_line=re.match(r'manager_url = ', line)
	if result_line is not None:
		param_manager_url=line.split(' = ')
		URL=param_manager_url[1]
	result_line=re.match(r'manager_connect_findmefollow', line)
	if result_line is not None:
		param_manager_connect_findmefollow=line.split(' = ')
		manager_connect_findmefollow=param_manager_connect_findmefollow[1]
	manager = Manager(loop=asyncio.get_event_loop(),
			host=manager_host,
			port=manager_port,
			username=manager_user,
			secret=manager_secret,
			ping_delay=5
			)
freepbx_pass.close()

time_h = datetime.strftime(datetime.now(), "%H")
time_m = datetime.strftime(datetime.now(), "%M")
day = datetime.strftime(datetime.now(), "%d")
all_minutes = int(time_h)*60+int(time_m)
i = int(manager_connect_findmefollow)
while i <= 1440:
        dict_connect_mysql_fw[i] = 0
        i = i + int(manager_connect_findmefollow)
time_connect_mysql(all_minutes)

#connect_findmefollow()

async def callback(mngr: panoramisk.Manager, msg: panoramisk.message) -> None:
        """Catch AMI Events/Actions"""

        if msg.event == 'FullyBooted':
                print('AMI Connection OK')
                log.info('AMI Connection OK')

        elif msg.event == "DialBegin":
####                print(msg.event)
                global dict_DialBegin
                if msg.DestUniqueid not in dict_DialBegin:
                        dict_DialBegin[msg.DestUniqueid] = dict()
                        dict_DialBegin[msg.DestUniqueid]['Timestamp'] = msg.Timestamp
                        dict_DialBegin[msg.DestUniqueid]['ConnectedLineNum'] = msg.ConnectedLineNum
                        dict_DialBegin[msg.DestUniqueid]['DestChannel'] = msg.DestChannel
                        dict_DialBegin[msg.DestUniqueid]['ChannelStateDesc'] = msg.ChannelStateDesc
                        dict_DialBegin[msg.DestUniqueid]['DestCallerIDNum'] = msg.DestCallerIDNum
                        dict_DialBegin[msg.DestUniqueid]['DestConnectedLineNum'] = msg.DestConnectedLineNum
                        dict_DialBegin[msg.DestUniqueid]['DestUniqueid'] = msg.DestUniqueid
                        dict_DialBegin[msg.DestUniqueid]['DestLinkedid'] = msg.DestLinkedid

        elif msg.event == "DialEnd":
####                print(msg.event)
                global dict_DialEnd
                if msg.DestUniqueid not in dict_DialEnd:
                        dict_DialEnd[msg.DestUniqueid] = dict()
                        dict_DialEnd[msg.DestUniqueid]['Timestamp'] = msg.Timestamp
                        dict_DialEnd[msg.DestUniqueid]['DestChannel'] = msg.DestChannel
                        dict_DialEnd[msg.DestUniqueid]['DestCallerIDNum'] = msg.DestCallerIDNum
                        dict_DialEnd[msg.DestUniqueid]['DestConnectedLineNum'] = msg.DestConnectedLineNum
                        dict_DialEnd[msg.DestUniqueid]['DestUniqueid'] = msg.DestUniqueid
                        dict_DialEnd[msg.DestUniqueid]['DestLinkedid'] = msg.DestLinkedid
                        dict_DialEnd[msg.DestUniqueid]['DialStatus'] = msg.DialStatus

        elif msg.event == "Hangup":
####                print(msg.event)
                global dict_Hangup
                if msg.Uniqueid not in dict_Hangup:
                        dict_Hangup[msg.Uniqueid] = dict()
                        dict_Hangup[msg.Uniqueid]['Timestamp'] = msg.Timestamp
                        dict_Hangup[msg.Uniqueid]['Channel'] = msg.Channel
                        dict_Hangup[msg.Uniqueid]['CallerIDNum'] = msg.CallerIDNum
                        dict_Hangup[msg.Uniqueid]['ConnectedLineNum'] = msg.ConnectedLineNum
                        dict_Hangup[msg.Uniqueid]['Uniqueid'] = msg.Uniqueid
                        dict_Hangup[msg.Uniqueid]['Linkedid'] = msg.Linkedid

                hangup_calls(str(msg.Uniqueid))

        time_h = datetime.strftime(datetime.now(), "%H")
        time_m = datetime.strftime(datetime.now(), "%M")
        all_minutes = int(time_h)*60+int(time_m)
        today = datetime.strftime(datetime.now(), "%d")
        global day
        if int(day) != int(today):
                day = today
                i = int(manager_connect_findmefollow)
                while i <= 1440:
                        dict_connect_mysql_fw[i] = 0
                        i = i + int(manager_connect_findmefollow)
        time_connect_mysql(all_minutes)
        
        pass

def main(mngr: panoramisk.Manager) -> None:
        mngr.register_event('*', callback=callback)
        mngr.connect()

        try:
                mngr.loop.run_forever()
        except (SystemExit, KeyboardInterrupt):
                mngr.loop.close()
                exit(0)

if __name__ == '__main__':
        main(manager)

