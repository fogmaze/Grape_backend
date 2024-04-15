from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import random
import json
import urllib.parse
import os
from typing import List, Tuple
from db import DataBaseOperator
import scorer_py as scorer
import gensim.downloader as api


Scores = scorer.Scores()
wv = api.load("word2vec-google-news-300")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

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
            method_name_str = parsed_query["method_name"][0]
            methods = method_name_str.split("|")
            tag_raw_str = parsed_query["tags"][0].replace("^","&")
            tags = decodeTags(tag_raw_str)
            tags_str = encodeTags(tags)
            isLoad = parsed_query["isLoad"][0] == "true"
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

            extraFilter = ""
            limit = 9999999
            if parsed_query["method_name"][0] == "notes" :
                extraFilter = "AND account='{}'".format(account)
            if parsed_query["tags"][0] == "random" :
                limit = 80
                print("random limit: ", limit)

            if (not isLoad) or (parsed_query["tags"][0] == "random"):
                for method_name in methods:
                    db_operator.cur.execute(f"SELECT time from {METHOD_NAME_TO_TABLE_NAME[method_name]} where {getFilter(tags)} {extraFilter} ORDER BY RANDOM() LIMIT {limit}")
                    print(getFilter(tags))
                    times = db_operator.cur.fetchall()
                    # get the results
                    for time in times:
                        if method_name in METHOD_HANDLER_DICT:
                            objs.append(METHOD_HANDLER_DICT[method_name](method_name, time[0]))
                        else :
                            objs.append(default_method_handler(method_name, time[0], account))
                    # shuffle the results
                random.shuffle(objs)
            else :
                db_operator.cur.execute("SELECT time,method_name FROM record_data WHERE id=?", (nowId,))
                results = db_operator.cur.fetchall()
                nonTested = []
                tested = []
                for time, method_name in results :
                    if method_name in METHOD_HANDLER_DICT:
                        nonTested.append(METHOD_HANDLER_DICT[method_name](method_name, time))
                    else :
                        nonTested.append(default_method_handler(method_name, time, account))
                for method_name in methods :
                    db_operator.cur.execute(f'SELECT time FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE {getFilter(tags)} {extraFilter} AND time NOT IN (SELECT time FROM record_data WHERE id={nowId}) ORDER BY RANDOM() LIMIT {limit}')
                    results = db_operator.cur.fetchall()
                    for time in results:
                        if method_name in METHOD_HANDLER_DICT:
                            tested.append(METHOD_HANDLER_DICT[method_name](method_name, time[0]))
                        else :
                            tested.append(default_method_handler(method_name, time[0], account))
                    random.shuffle(tested)
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
            for obj in objs:
                db_operator.cur.execute("INSERT INTO record_data (id, method_name, time) VALUES (?, ?, ?)", (nowId, obj["name"], obj["time"]))
            # save to settings
            db_operator.cur.execute("UPDATE settings SET te_methods=?, te_tags=?, te_lp=?, te_level=? WHERE account=?", (method_name_str, tags_str, 1 if parsed_query["isLoad"][0] == "true" else 0, int(parsed_query["level"][0]), account))

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
            db_operator.cur.execute("SELECT te_methods,te_tags,te_lp,te_level FROM settings WHERE account=?", (parsed_query["account"][0],))
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
                    "lp": str(result[2]),
                    "level": str(result[3])
                }
            db_operator.close()
        
        elif parsed_query["type"][0] == "note" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT time FROM notes WHERE method_name=? AND method_time=? AND account=?", (parsed_query["method_name"][0], int(parsed_query["method_time"][0]), parsed_query["account"][0]))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                db_operator.cur.execute(f'INSERT INTO notes (method_name, method_time, tags, time, account) VALUES (?, ?, (SELECT tags FROM {METHOD_NAME_TO_TABLE_NAME[parsed_query["method_name"][0]]} WHERE time={int(parsed_query["method_time"][0]) }), strftime("%s","now"), ?)', (parsed_query["method_name"][0], int(parsed_query["method_time"][0]), parsed_query["account"][0]))
                response = {
                    "status": "success"
                }
            else :
                response = {
                    "status": "already added"
                }

            db_operator.close()
        
        elif parsed_query["type"][0] == "unote" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("DELETE FROM notes WHERE time=?", (int(parsed_query["time"][0]),))
            response = {
                "status": "success"
            }
            db_operator.close()

        elif parsed_query["type"][0] == "createAccount" :
            db_operator = DataBaseOperator()
            db_operator.cur.execute("SELECT account FROM settings WHERE account=?", (parsed_query["account"][0],))
            result = db_operator.cur.fetchall()
            if len(result) == 0:
                db_operator.cur.execute("INSERT INTO settings (account, te_methods, te_tags, te_lp, te_level) VALUES (?, ?, ?, ?, ?)", (parsed_query["account"][0], "", "", 0, 0))
                response = {
                    "status": "success"
                }
            else :
                response = {
                    "status": "failed"
                }
            db_operator.close()

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
            with open("interface" + self.path, "wb") as f:
                f.write(post_data)
            
            # send status code
            self.send_response(200)
            self.send_header("Content-type", "plain/text")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept", "*/*")
            self.end_headers()
            if "highSchool.db" in self.path:
                scorer.startScoring(scores=Scores, wv=wv)
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
    method_name = result[0][0]
    method_time = result[0][1]
    if method_name in METHOD_HANDLER_DICT:
        actual = METHOD_HANDLER_DICT[method_name](method_name, method_time)
    else :
        actual = default_method_handler(method_name, method_time, account=account)
    ret = {
        "name": "notes",
        "time": time,
        "actual": actual,
    }
    return ret

def en_voc_method_handler(method_name, time, account="") :
    # get the cursor
    db_operator = DataBaseOperator()
    # execute the query
    sql_str = f"SELECT que,ans,tags,testing_blacklist,id FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE time = {time}"
    db_operator.cur.execute(sql_str)
    # get the results
    results = db_operator.cur.fetchall()

    related = []
    weights = []
    que_id = results[0][4]
    for i in range(Scores.n+1) :
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
        for j in range(Scores.n+1) :
            r -= weights[j]
            if r <= 0 :
                db_operator.cur.execute(f"SELECT time FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE id = {j}")
                time_related = db_operator.cur.fetchone()[0]
                related.append(default_method_handler(method_name, time_related, account=account))
                break

    db_operator.cur.execute(f"SELECT time FROM notes WHERE method_time={time}")
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
        "related": related
    }

    db_operator.close()

    return ret
 
def default_method_handler(method_name, time, account="") :
    # get the cursor
    db_operator = DataBaseOperator()
    # execute the query
    sql_str = f"SELECT que,ans,tags,testing_blacklist FROM {METHOD_NAME_TO_TABLE_NAME[method_name]} WHERE time = {time}"
    db_operator.cur.execute(sql_str)
    
    db_operator.cur.execute(f"SELECT time FROM notes WHERE method_time={time}")
    note_time = db_operator.cur.fetchall()
    
    if len(note_time) > 0:
        note_time = note_time[0][0]
    else :
        note_time = 0
    # get the results
    results = db_operator.cur.fetchall()

    db_operator.close()
    ret = {
        "name": method_name,
        "time": time,
        "que": results[0][0],
        "ans": results[0][1],
        "tags": results[0][2],
        "tb": results[0][3],
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

def getFilter(tags, minLevel=-1)->str:
    tagLimit_d = tags
    if len(tagLimit_d) == 0:
        return ""

    tag_limits = []
    for lim in tagLimit_d:
        condition = []
        for tag in lim:
            if tag == "|random|":
                return "True"
            condition.append('tags like "%{}%"'.format(tag))
        tag_limits.append('(' + " AND ".join(condition) + ")")
    tag_limits = '(' + ' OR '.join(tag_limits) + ')'
    result = ""
    result += tag_limits + " AND level >= {}".format(minLevel)
    return result

METHOD_NAME_TO_TABLE_NAME = {
    "en_voc_def": "en_voc",
    "en_voc_spe": "en_voc",
    "en_prep_def": "en_prep",
    "en_prep_spe": "en_prep",
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

RELATED_NUM = 4
NOTED_EXTRA_WEIGHT = 3
if __name__ == "__main__":
    
    run(port=8000)
