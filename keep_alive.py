from threading import Thread 
from flask import Flask 

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive", 200   # keep simple text at root

@app.route('/ping')
def ping():
    return "OK", 200   # lightweight route for cron-job.org

def run_http_server():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_http_server)
    t.start()
