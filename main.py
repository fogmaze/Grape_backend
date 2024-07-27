from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
import Levenshtein
import threading
import socket
import random
import json
import urllib.parse
import os
from typing import List, Tuple
from db import DataBaseOperator
import scorer_py as scorer
import gensim.downloader as api
import argparse
import time as time_module


Scores = scorer.Scores()
wv = None# = api.load("word2vec-google-news-300")
searchRecords = []

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def handle_getSentence(self, query) :
        word = query["word"][0]
        meaning = query["meaning"][0]
        s = getSentence(word, meaning)
        return {
            "status": "success",
            "sentence": s
        }

    def handle_regenerateSentence(self, query) :
        word = query["word"][0]
        meaning = query["meaning"][0]
        s = reGenerateSentence(word, meaning)
        return {
            "status": "success",
            "sentence": s
        }


    def do_GET(self):
        response = {}
        # get the the query
        query = urllib.parse.urlparse(self.path).query
        # parse the query
        parsed_query = urllib.parse.parse_qs(query)
        if "type" not in parsed_query:
            pass
        elif parsed_query["type"][0] == "reget" :

            ret_value = []
            account = parsed_query["account"][0]
            if "method_name" not in parsed_query:
                return
            method_name_str = parsed_query["method_name"][0]
            methods = method_name_str.split("|")
            tag_raw_str = parsed_query["tags"][0].replace("^","&")
            tags = decodeTags(tag_raw_str)
            tags_str = encodeTags(tags)
            isLoad = parsed_query["isLoad"][0] == "true"
            minLevel = int(parsed_query["minLevel"][0])
            maxLevel = int(parsed_query["maxLevel"][0])

            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT id from record_list WHERE method_names=? AND tags=? AND account=?", (method_name_str, tags_str, account))
            ids = db_operator.cur.fetchall()
            if len(ids) == 0:
                ret_value.append("no record found")
                db_operator.cur.execute("insert into record_list (method_names, tags, account) values (?, ?, ?)", (method_name_str, tags_str, account))
                db_operator.con.commit()
                db_operator.cur.execute("SELECT id from record_list WHERE method_names=? AND tags=? AND account=?", (method_name_str, tags_str, account))
                nowId = db_operator.cur.fetchall()[0][0]
            else :
                nowId = ids[0][0]

            objs = []
            nowTestingIdx = 0

            limit = 9999999
            noteExtraFilter = "AND account='{}' AND method_name NOT LIKE 'en_prep%'".format(account)
            if parsed_query["tags"][0] == "random" :
                limit = 20
                print("random limit: ", limit)

            if (not isLoad) or (parsed_query["tags"][0] == "random"):
                for method_name in methods:
                    extraFilter = ""
                    if (method_name == "notes"):
                        extraFilter = noteExtraFilter
                    db_operator.cur.execute(f"SELECT time from {METHOD_NAME_TO_TABLE_NAME[method_name]} where {getFilter(tags, (minLevel, maxLevel))} {extraFilter} ORDER BY RANDOM() LIMIT {limit}")
                    times = db_operator.cur.fetchall()
                    # get the results
                    for t in times:
                        if method_name in METHOD_HANDLER_DICT:
                            objs.append(METHOD_HANDLER_DICT[method_name](method_name, t[0], account))
                        else :
                            objs.append(default_method_handler(method_name, t[0], account))
                        # remove the None objects
                        objs = [obj for obj in objs if obj is not None]
                    # shuffle the results
                random.shuffle(objs)
            else :
                db_operator.cur.execute("SELECT time,method_name FROM record_data WHERE id=?", (nowId,))
                results = db_operator.cur.fetchall()
                nonTested = []
                tested = []
                for time, method_name in results :
                    if method_name in METHOD_HANDLER_DICT:
                        nonTested.append(METHOD_HANDLER_DICT[method_name](method_name, time, account=account))
                    else :
                        nonTested.append(default_method_handler(method_name, time, account))
                for method_name in methods :
                    if method_name == "":
                        continue
                    extraFilter = ""
                    if (method_name == "notes"):
                        extraFilter = noteExtraFilter
                    db_operator.cur.execute(f'SELECT time FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE {getFilter(tags, (minLevel, maxLevel))} {extraFilter} AND time NOT IN (SELECT time FROM record_data WHERE id={nowId}) ORDER BY RANDOM() LIMIT {limit}')
                    results = db_operator.cur.fetchall()
                    for time in results:
                        if method_name in METHOD_HANDLER_DICT:
                            tested.append(METHOD_HANDLER_DICT[method_name](method_name, time[0], account=account))
                        else :
                            tested.append(default_method_handler(method_name, time[0], account))
                    random.shuffle(tested)
                # remove the None objects
                tested = [obj for obj in tested if obj is not None]
                nonTested = [obj for obj in nonTested if obj is not None]
                objs = tested + nonTested
                nowTestingIdx = len(tested)
                if len(objs) == nowTestingIdx :
                    nowTestingIdx = 0
            response = {
                "id": nowId,
                "data": objs,
                "nowTestingIdx": nowTestingIdx
            }
            # save to database
            db_operator.cur.execute("DELETE FROM record_data WHERE id=?", (nowId,))
            for obj in objs[nowTestingIdx:]:
                db_operator.cur.execute("INSERT INTO record_data (id, method_name, time) VALUES (?, ?, ?)", (nowId, obj["name"], obj["time"]))
            # save to settings
            db_operator.cur.execute("UPDATE settings SET te_methods=?, te_tags=?, te_lp=?, te_level=?, te_level_max=? WHERE account=?", (method_name_str, tags_str, 1 if parsed_query["isLoad"][0] == "true" else 0, int(parsed_query["minLevel"][0]), int(parsed_query["maxLevel"][0]), account))

            db_operator.close()

        elif parsed_query["type"][0] == "update_rec" :
            db_operator = DataBaseOperator()
            operation = parsed_query["operation"][0]
            targetId = parsed_query["targetId"][0]
            
            if operation == "del" :
                time = parsed_query["time"][0]
                method_name = parsed_query["method_name"][0]
                db_operator.cur.execute("DELETE FROM record_data WHERE id=? AND time=? AND method_name=?", (targetId, time, method_name))
                print("deleting record: ", targetId, time, method_name)
            else :
                print("operation not supported: ", operation)

            db_operator.close()

        elif parsed_query["type"][0] == "getParam" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT te_methods,te_tags,te_lp,te_level,te_level_max FROM settings WHERE account=?", (parsed_query["account"][0],))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                response = {
                    "hasAccount": "false"
                }
            else :
                result = result[0]
                response = {
                    "methods": result[0],
                    "tags": result[1],
                    "lp": "1",
                    "level": str(result[3]),
                    "level_max": str(result[4]),
                }
            db_operator.close()
        
        elif parsed_query["type"][0] == "note" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT time FROM notes WHERE method_name=? AND method_time=? AND account=?", (parsed_query["method_name"][0], int(parsed_query["method_time"][0]), parsed_query["account"][0]))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                nowTime = int(time_module.time())
                db_operator.cur.execute(f'INSERT INTO notes (method_name, method_time, tags, time, account, level) VALUES (?, ?, (SELECT tags FROM {METHOD_NAME_TO_TABLE_NAME[parsed_query["method_name"][0]]} WHERE time={int(parsed_query["method_time"][0]) }), ?, ?, (SELECT level FROM {METHOD_NAME_TO_TABLE_NAME[parsed_query["method_name"][0]]} WHERE time={int(parsed_query["method_time"][0]) }))', (parsed_query["method_name"][0], int(parsed_query["method_time"][0]), nowTime, parsed_query["account"][0]))
                note_time = db_operator.cur.fetchall()
                response = {
                    "status": "success",
                    "time": nowTime
                }
            else :
                response = {
                    "status": "already added"
                }

            db_operator.close()
        
        elif parsed_query["type"][0] == "unote" :
            print("unote")
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT method_name,method_time FROM notes WHERE time=?", (int(parsed_query["time"][0]),))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                response = {
                    "status": "failed"
                }
            else:
                db_operator.cur.execute(f"SELECT que from {METHOD_NAME_TO_TABLE_NAME[result[0][0]]} WHERE time={result[0][1]}")
                print("unote: " , db_operator.cur.fetchall())
                db_operator.cur.execute("DELETE FROM notes WHERE time=?", (int(parsed_query["time"][0]),))
                response = {
                    "status": "success"
                }
                print("unote: ", parsed_query["time"][0])
            db_operator.close()

        elif parsed_query["type"][0] == "createAccount" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT account FROM settings WHERE account=?", (parsed_query["account"][0],))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                db_operator.cur.execute("INSERT INTO settings (account, te_methods, te_tags, te_lp, te_level, te_level_max) VALUES (?, ?, ?, ?, ?, 6)", (parsed_query["account"][0], "", "", 0, 0))
                response = {
                    "status": "success"
                }
            else :
                response = {
                    "status": "failed"
                }
            db_operator.close()

        elif parsed_query["type"][0] == "search" :
            db_operator = DataBaseOperator()
            que = parsed_query["que"][0]
            result = []

            db_operator.cur.execute('SELECT que,ans FROM {} WHERE que LIKE "%{}%" ORDER BY TIME'.format("en_voc",que))
            similar_data = db_operator.cur.fetchall()

            if len(similar_data) > 0:
                if similar_data == searchRecords:
                    response = {
                        "status": "same"
                    }
                else :
                    response = {
                        "status": "success",
                        "data": sorted(similar_data, key=lambda x: Levenshtein.distance(que, x[0]))[0:5]
                    }
            else:
                response = {
                    "status": "fail"
                }
            db_operator.close()
        
        elif parsed_query["type"][0] == "add" :
            db_operator = DataBaseOperator()
            que = parsed_query["que"][0]
            ans = parsed_query["ans"][0]
            if not "tags" in parsed_query:
                tags = ""
            else:
                tags = parsed_query["tags"][0]
            
            db_operator.cur.execute("SELECT tags FROM en_voc WHERE que=?", (que,))
            old_tags = db_operator.cur.fetchall()
            if len(old_tags) > 0:
                finalTags = mergeEncodedTags(("|" + tags + "|", old_tags[0][0])) + "|"
                db_operator.cur.execute("UPDATE en_voc SET ans=?, tags=? WHERE que=?", (ans, finalTags, que))
            else :
                finalTags = "|" + tags + "|"
                db_operator.cur.execute("INSERT INTO en_voc (que, ans, tags, time, level) VALUES (?, ?, ?, strftime('%s','now'), ?)", (que, ans, finalTags, getLevelFromWord(que)))
            
            db_operator.close()
            response = {
                "status": "success"
            }
        
        elif parsed_query["type"][0] == "finishWriting" :
            scoreThread = threading.Thread(target=scorer.startScoring, args=(Scores, wv))
            scoreThread.start()
            updateTagList()
            response = {
                "status": "success"
            }

        elif parsed_query["type"][0] == "getTags" :
            response = {
                "tags": getTagList()
            }
        
        elif parsed_query["type"][0] == "getSentence" :
            response = self.handle_getSentence(parsed_query)
        elif parsed_query["type"][0] == "RegenerateSentence":
            response = self.handle_regenerateSentence(parsed_query)


        if "type" in parsed_query :
            # send status code
            self.send_response(200)
            self.send_header("Content-type", "plain/text")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept", "*/*")
            self.end_headers()
            # send the response
            self.wfile.write(json.dumps(response).encode('utf-8'))

        # handle the file request
        else:
            # get the file path
            path = os.path.join(os.getcwd(), "interface", self.path[1:])
            if path.endswith("/"):
                path += "index.html"
            # check if the file exists
            if os.path.exists(path):
                # send status code
                self.send_response(200)
                # send the content type
                if path.endswith(".html"):
                    self.send_header("Content-type", "text/html")
                elif path.endswith(".js"):
                    self.send_header("Content-type", "application/javascript")
                elif path.endswith(".css"):
                    self.send_header("Content-type", "text/css")
                elif path.endswith(".png"):
                    self.send_header("Content-type", "image/png")
                elif path.endswith(".json"):
                    self.send_header("Content-type", "application/json")
                elif path.endswith(".ico"):
                    self.send_header("Content-type", "image/x-icon")
                else :
                    self.send_header("Content-type", "octet-stream")
                self.end_headers()
                # send the file content
                with open(path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                # send status code
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"404 Not Found")

    def do_POST(self):
        
        # get the the query
        query = urllib.parse.urlparse(self.path).query
        print("post query: ", query)
        # parse the query
        parsed_query = urllib.parse.parse_qs(query)
        # get the json code form the body
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        if "type" not in parsed_query:
            # save the file into datas folder
            if not os.path.isdir("interface" + os.path.dirname(self.path)):
                os.makedirs("interface" + os.path.dirname(self.path))
            with open("interface" + self.path, "wb") as f:
                f.write(post_data)
            
            # send status code
            self.send_response(200)
            self.send_header("Content-type", "plain/text")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept", "*/*")
            self.end_headers()
            if "highSchool.db" in self.path:
                isScoring = True
                scorer.startScoring(scores=Scores, wv=wv)
                isScoring = False
                updateTagList()
            return

        json_data = json.loads(post_data)


        if parsed_query["type"][0] == "update_rec" :
            db_operator = DataBaseOperator()
            operation = parsed_query["operation"][0]
            targetId = parsed_query["targetId"][0]
            print("operation: ", operation)
            if operation == "reset" :
                print("resetting record: ", targetId)
                method_names = json_data["method_names"]
                times = json_data["times"]
                db_operator.cur.execute("DELETE FROM record_data WHERE id=?", (targetId,))
                # add method_names and times to record_data
                for i in range(len(method_names)):
                    db_operator.cur.execute("INSERT INTO record_data (id, method_name, time) VALUES (?, ?, ?)", (targetId, method_names[i], times[i]))
            db_operator.close()
                
        self.send_response(200)
        self.send_header("Content-type", "plain/text")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept", "*/*")
        self.end_headers()


def run(server_class=HTTPServer, handler_class=SimpleHTTPRequestHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    httpd.socket.settimeout(60)
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 50000)
    print(f"Server started on port {port}")
    httpd.serve_forever()


def notes_method_handler(method_name, time, account="") :
    db_operator = DataBaseOperator()
    db_operator.cur.execute(f"SELECT method_name, method_time FROM notes WHERE time = {time}")
    result = db_operator.cur.fetchall()
    db_operator.close()
    if (len(result) == 0):
        return None
    method_name = result[0][0]
    method_time = result[0][1]
    if method_name in METHOD_HANDLER_DICT:
        actual = METHOD_HANDLER_DICT[method_name](method_name, method_time, account=account)
    else :
        actual = default_method_handler(method_name, method_time, account=account)
    if actual is None:
        return None
    ret = {
        "name": "notes",
        "time": time,
        "level": actual["level"],
        "actual": actual,
    }
    return ret

def en_voc_method_handler(method_name, time, account="") :
    # get the cursor
    db_operator = DataBaseOperator()
    # execute the query
    sql_str = f"SELECT que,ans,tags,testing_blacklist,id,level FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE time = {time}"
    db_operator.cur.execute(sql_str)
    # get the results
    results = db_operator.cur.fetchall()

    related = []
    weights = []
    if len(results) == 0:
        print("no result found for ", method_name, time)
        return None
    que_id = results[0][4]
    for i in range(len(Scores)+1) :
        if i != que_id :
            weights.append(Scores.get(que_id, i))
        else :
            weights.append(0)
    

    db_operator.cur.execute(f"SELECT id FROM en_voc WHERE time IN (SELECT method_time FROM notes WHERE method_name='{method_name}')")
    noted_ids = db_operator.cur.fetchall()
    for noted_id in noted_ids :
        weights[noted_id[0]-1] * NOTED_EXTRA_WEIGHT
    
    weightsSum = sum(weights)
    for i in range(RELATED_NUM) :
        r = random.random() * weightsSum
        for j in range(len(Scores)+1) :
            r -= weights[j]
            if r <= 0 :
                db_operator.cur.execute(f"SELECT time FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE id = {j}")
                time_related = db_operator.cur.fetchone()
                if time_related is None:
                    print("id not found: ", j)
                    break
                time_related = time_related[0]
                related.append(default_method_handler(method_name, time_related, account=account))
                break

    db_operator.cur.execute(f"SELECT time FROM notes WHERE method_time={time} AND method_name='{method_name}' AND account='{account}'")
    note_time = db_operator.cur.fetchall()
    if len(note_time) > 0:
        note_time = note_time[0][0]
    else :
        note_time = 0
    ret = {
        "name": method_name,
        "time": time,
        "que": results[0][0],
        "ans": results[0][1],
        "tags": results[0][2],
        "tb": results[0][3],
        "note_time": note_time,
        "level": results[0][5],
        "related": related
    }

    db_operator.close()

    return ret
 
def default_method_handler(method_name, time, account="") :
    # get the cursor
    db_operator = DataBaseOperator()
    # execute the query
    sql_str = f"SELECT que,ans,tags,testing_blacklist,level FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE time = {time}"
    db_operator.cur.execute(sql_str)
    # get the results
    results = db_operator.cur.fetchall()
    
    db_operator.cur.execute(f"SELECT time FROM notes WHERE method_time={time} AND account='{account}'")
    note_time = db_operator.cur.fetchall()
    
    if len(note_time) > 0:
        note_time = note_time[0][0]
    else :
        note_time = 0

    db_operator.close()
    ret = {
        "name": method_name,
        "time": time,
        "que": results[0][0],
        "ans": results[0][1],
        "tags": results[0][2],
        "tb": results[0][3],
        "level": results[0][4],
        "note_time": note_time,
        "related": []
    }
    return ret
    
def decodeList(str:str) -> List[str]:
    if str == "":
        return []
    return str.split('|')
def encodeList(list:List[str]) -> str:
    return '|'.join(list)
def mergeEncodedList(strs:Tuple[str]):
    all_tags = []
    for str in strs:
        all_tags_in_str = decodeList(str)
        for tag in all_tags_in_str:
            if tag not in all_tags:
                all_tags.append(tag)
    return encodeList(all_tags)

def decodeTags(tagss:str) -> List[List[str]]:
    print("decode input: ",tagss)
    res = []
    tags = decodeList(tagss)
    for tag in tags:
        res.append(["|" + t + "|" for t in tag.split('&')])
    print("decode output: ",res)
    return res

def encodeTags(list:List[List[str]]) -> str:
    print("encode input: ",list)
    tags_strs = []
    for tag in list:
        tags_strs.append('&'.join([t.replace("|",'') for t in tag]))
    print("encode output: ",tags_strs)
    return encodeList(tags_strs)

def mergeEncodedTags(strs:Tuple[str]):
    all_tags = []
    for str in strs:
        all_tags_in_str = decodeTags(str)
        for tag in all_tags_in_str:
            if tag not in all_tags:
                all_tags.append(tag)
    return encodeTags(all_tags)

def getFilter(tags, levelRange)->str:
    tagLimit_d = tags
    if len(tagLimit_d) == 0:
        return ""

    tag_limits = []
    for lim in tagLimit_d:
        condition = []
        for tag in lim:
            if tag == "|random|":
                return "level >= {} AND level <= {}".format(levelRange[0], levelRange[1])
            condition.append('tags like "%{}%"'.format(tag))
        tag_limits.append('(' + " AND ".join(condition) + ")")
    tag_limits = '(' + ' OR '.join(tag_limits) + ')'
    result = ""
    result += tag_limits + " AND level >= {} AND level <= {}".format(levelRange[0], levelRange[1])
    return result

def updateTagList() :
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT tags, time FROM en_voc ORDER BY time DESC")
    tags :List[str]= db_operator.cur.fetchall()
    result = {}
    for (tag, time) in tags:
        if "mag" in tag and not "other" in tag:
            if len(tag.split("|")) == 5 and "-" not in tag:
                if tag not in result:
                    result[tag] = time
            elif len(tag.split("|")) == 4:
                if tag not in result:
                    result[tag] = time
        if ("ea" in tag or "build" in tag) and len(tag.split("|")) == 4:
            if tag not in result:
                result[tag] = time
        if "tb" in tag and not "other" in tag:
            if len(tag.split("|")) == 5 and "-" not in tag:
                if tag not in result:
                    result[tag] = time
            elif len(tag.split("|")) == 4:
                if tag not in result:
                    result[tag] = time
    
    db_operator.cur.execute("DELETE FROM tag_list")
    for tag in result:
        db_operator.cur.execute("INSERT INTO tag_list (tag, time) VALUES (?, ?)", (tag, result[tag]))
    extra = ["other", "GSAT"]
    for tag in extra:
        db_operator.cur.execute("INSERT INTO tag_list (tag, time) VALUES (?, strftime('%s','now'))", (tag,))
    db_operator.close()

def getTagList() -> List[str]:
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT tag FROM tag_list ORDER BY time DESC")
    tags = db_operator.cur.fetchall()
    result = []
    for (tag,) in tags:
        if "|" in tag:
            result.append("&".join(tag.split("|")[1:-1]))
        else :
            result.append(tag)
    db_operator.close()
    return result

def loadWV() :
    global wv
    tmp = api.load("word2vec-google-news-300")
    wv = tmp

def getLevelFromWord(word:str) -> int:
    spl = word.split(" ")
    maxLevel = 0
    for w in spl:
        tar = [w]
        if "ly" in w:
            tar.append(w[:-2])
        if "ed" in w:
            tar.append(w[:-2])
            tar.append(w[:-1])
        if "ness" in w:
            tar.append(w[:-4])
        if "ing" in w:
            tar.append(w[:-3])
        if "ful" in w:
            tar.append(w[:-3])
            tar.append(w[2:])
        if "re" in w or "un" in w or "in" in w or "im" in w or "ir" in w or "il" in w:
            tar.append(w[2:])
        tar.append(w+"(ment)")

        for t in tar:
            for i in range(1, 7) :
                if t in wordList[str(i)]:
                    if i > maxLevel:
                        maxLevel = i
    return maxLevel

def updateUnAdded() :
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT que FROM en_voc")
    result = db_operator.cur.fetchall()

    for (que,) in result:
        spl = que.split(" ")
        maxLevel = 0
        stdWord = ""
        for w in spl:
            tar = [w]
            if "ly" in w:
                tar.append(w[:-2])
            if "ed" in w:
                tar.append(w[:-2])
                tar.append(w[:-1])
            if "ness" in w:
                tar.append(w[:-4])
            if "ing" in w:
                tar.append(w[:-3])
            if "ful" in w:
                tar.append(w[:-3])
                tar.append(w[2:])
            if "re" in w or "un" in w or "in" in w or "im" in w or "ir" in w or "il" in w:
                tar.append(w[2:])
            tar.append(w+"(ment)")

            for t in tar:
                for i in range(1, 7) :
                    if t in wordList[str(i)]:
                        if i > maxLevel:
                            maxLevel = i
                            stdWord = t
        
        db_operator.cur.execute("UPDATE std SET has=1 WHERE word=?", (stdWord,))
    db_operator.close()

def updateLevel() :
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT que FROM en_voc")
    result = db_operator.cur.fetchall()
    for (que,) in result:
        level = getLevelFromWord(que)
        print(que, level)
        db_operator.cur.execute("UPDATE en_voc SET level=? WHERE que=?", (getLevelFromWord(que), que))

    db_operator.cur.execute("SELECT method_name, method_time FROM notes")
    result = db_operator.cur.fetchall()
    for (method_name, method_time) in result:
        db_operator.cur.execute(f"SELECT que FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE time={method_time}")
        que = db_operator.cur.fetchall()
        if len(que) > 0:
            que = que[0][0]
            db_operator.cur.execute("UPDATE notes SET level=? WHERE method_time=?", (getLevelFromWord(que), method_time))
    
    db_operator.close()

def getSentence(word, meaning): 
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT sentence,ans FROM en_voc WHERE que=?", (word,))
    result = db_operator.cur.fetchall()
    db_operator.close()
    if len(result) == 0:
        return "err: no sentence found"
    if result[0][0] == "Generating":
        meanings = result[0][1].split("|")
        db_operator = DataBaseOperator()
        db_operator.cur.execute("UPDATE en_voc SET sentence=? WHERE que=?", ("|".join(["Ungenerated"]*len(meanings)), word))
        db_operator.close()
        return reGenerateSentence(word, meaning)
    sentences = result[0][0].split("|")
    meanings = result[0][1].split("|")
    for i in range(len(sentences)):
        if meaning == meanings[i]:
            if sentences[i] == "Ungenerated":
                return reGenerateSentence(word, meaning)
            return sentences[i]
    return "err: meaning not matched"

def reGenerateSentence(word, meaning):
    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT sentence,ans FROM en_voc WHERE que=?", (word,))
    result = db_operator.cur.fetchall()
    if len(result) == 0:
        db_operator.close()
        return "err: no sentence found"
    sentences = result[0][0].split("|")
    meanings = result[0][1].split("|")
    for i in range(len(sentences)):
        if meaning == meanings[i]:
            respond_sentence = requestSentence(word, meaning)
            sentences[i] = respond_sentence
            new_sentence_str = "|".join(sentences)
            db_operator.cur.execute("UPDATE en_voc SET sentence=? WHERE que=?", (new_sentence_str, word))
            db_operator.close()
            return respond_sentence
    db_operator.close()
    return "err: meaning not matched"

def requestSentence(word, meaning) -> str:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You will receive a word and it's Chinese meaning, please provide a very short example sentence."
                },
                {
                    "role": "user",
                    "content": word + "/" + meaning
                }
            ]
        }
    )
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]

with open("configure.json", "r") as f:
    configureJson = json.load(f)
    OPENAI_API_KEY = configureJson["OPENAI_API_KEY"]

METHOD_NAME_TO_TABLE_NAME = {
    "en_voc_def": "en_voc",
    "en_voc_spe": "en_voc",
    "en_prep_def": "en_prep",
    "en_prep_spe": "en_prep",
    "en_prep_ans": "en_prep",
    "notes": "notes",
}

EMPTY_RELATED = {
    "name": "en_voc_def",
    "time": 0,
    "que": "developing",
    "ans": "developing",
    "tags": "developing",
}

METHOD_HANDLER_DICT = {
    "notes": notes_method_handler,
    "en_voc_def": en_voc_method_handler,
    "en_voc_spe": en_voc_method_handler,
}
with open("wordList.json", "r") as f:
    wordList = json.load(f)

RELATED_NUM = 4
NOTED_EXTRA_WEIGHT = 3

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-pre", "--pre", help="pre", action="store_true")
    args = parser.parse_args()

    if args.pre:
        loadWV()
    
    run(port=8000)
