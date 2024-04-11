import os
import sqlite3 as sql

db_path = "interface/highSchool.db"
class DataBaseOperator():
    def __init__(self):
        if not os.path.isfile(db_path):
            raise Exception("database file not found")
        self.con = sql.connect(db_path)
        self.cur = self.con.cursor()
    def close(self):
        self.con.commit()
        self.cur.close()
        self.con.close()