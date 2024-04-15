import gensim.downloader as api
from db import DataBaseOperator
import tqdm
import Levenshtein
import pickle
import numpy as np


data_filename = "interface/data_np.pkl"

class Scores: 
    def __init__(self):
        with open(data_filename, "rb") as f:
            self.data:np.ndarray = pickle.load(f)
            self.n = len(self.data)
    
    def put(self, i, j, val):
        if i >= len(self.data) or j >= len(self.data):
            old_data = self.data
            self.data = np.zeros((max(i, j)+1, max(i, j)+1))
            self.data[:len(old_data), :len(old_data)] = old_data
        self.data[max(i, j)][min(i, j)] = val
        self.data[min(i, j)][max(i, j)] = val
    
    def normalize(self):
        for i in range(len(self.data)):
            sum = np.sum(self.data[i])
            if sum == 0:
                continue
            self.data[i] = self.data[i] / sum

    def get(self, target, item):
        if target >= len(self.data) or item >= len(self.data):
            return 0.0
        return self.data[item][target]
    
    def save(self):
        with open(data_filename, "wb") as f:
            pickle.dump(self.data, f)

def startScoring(scores:Scores = None, wv = None):
    with open(data_filename, "wb") as f:
        pickle.dump(np.array([]), f)
    if scores is None:
        scores = Scores()
    if wv is None:
        wv = api.load("word2vec-google-news-300")

    db_operator = DataBaseOperator()
    db_operator.cur.execute("SELECT id FROM en_voc ORDER BY id DESC LIMIT 1")
    result = db_operator.cur.fetchone()
    scores.put(1, result[0], 0.0)
    for i in tqdm.tqdm(range(scores.n-1, result[0]+1)):
        for j in range(1, i):
            if scores.get(i, j) <= 0:
                db_operator.cur.execute("SELECT que FROM en_voc WHERE id = ?", (i,))
                word1 = db_operator.cur.fetchone()[0]
                db_operator.cur.execute("SELECT que FROM en_voc WHERE id = ?", (j,))
                word2 = db_operator.cur.fetchone()[0]
                score = 0
                try: 
                    score = wv.similarity(word1, word2)
                except:
                    pass
                dis_score = (1-Levenshtein.distance(word1, word2)/ max(len(word1), len(word2))) * 0.5
                score += dis_score
                scores.put(i, j, score*score*score*score*score)
    scores.normalize()
    db_operator.close()
    scores.save()

if __name__ == "__main__":
    startScoring()