"""16-way queue around the unchanged training fitter."""
import os
from http.server import ThreadingHTTPServer
from shared import *
import grader
grader.POOL.shutdown();grader.POOL=Pool('fit',16)
class Handler(grader.Handler):
    def do_GET(self):
        if self.path=='/concurrency':self.reply(grader.POOL.metrics());return
        return super().do_GET()
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.environ['GRADER_PORT'])),Handler).serve_forever()
