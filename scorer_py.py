import gensim.downloader as api
from db import DataBaseOperator
import tqdm
import Levenshtein
import pickle



class Scores:
    def __init__(self):
        with open("data.pkl", "rb") as f:
            self.data = pickle.load(f)
            self.n = len(self.data)

    def put(self, i, j, val):
        if i >= len(self.data) or j >= len(self.data):
            for x in range(len(self.data), max(i, j)+1):
                self.data.append([0.0] * x)
                self.n += 1
        self.data[max(i, j)][min(i, j)] = val

    def get(self, i, j):
        if i >= len(self.data) or j >= len(self.data):
            return 0.0
        return self.data[max(i, j)][min(i, j)]

    def save(self):
        with open("data.pkl", "wb") as f:
            pickle.dump(self.data, f)

def startScoring(scores: Scores):
    wv = api.load("word2vec-google-news-300")

    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT id FROM en_voc ORDER BY id DESC LIMIT 1")
    result = db_operator.cur.fetchone()
    for i in tqdm.tqdm(range(1, result[0]+1)):
        for j in range(1, i):
            if scores.get(i, j) <= 0:
                db_operator.cur.execute("SELECT que FROM en_voc WHERE id = ?", (i,))
                word1 = db_operator.cur.fetchone()[0]
                db_operator.cur.execute("SELECT que FROM en_voc WHERE id = ?", (j,))
                word2 = db_operator.cur.fetchone()[0]
                try: 
                    score = wv.similarity(word1, word2)
                except:
                    score = 1-Levenshtein.distance(word1, word2)/ max(len(word1), len(word2))
                scores.put(i, j, score*score*score*score)
    db_operator.close()
    scores.save()




if __name__ == "__main__" :
    pass
