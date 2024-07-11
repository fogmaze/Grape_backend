import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

process = None
def runProcess() :
    global process
    process = subprocess.Popen(['python3', 'main.py', '--pre'])
class ResetHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.reset()
        self.wfile.write(b"Reseted")
        return

    def reset(self):
        global process
        if process is not None:
            print("Terminating process")
            process.terminate()
            process.wait(10)
            print("Terminated")

            if process.poll() is None:
                print("Killing process")
                process.kill()
                process.wait(3)
            
            process = None
            runProcess()

    
def run():
    server_address = ('', 8001)
    httpd = HTTPServer(server_address, ResetHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    runProcess()
    try: 
        run()
    except KeyboardInterrupt:
        process.terminate()
        process.wait(10)
        if process.poll() is None:
            process.kill()
            process.wait(3)
        print("Terminated")