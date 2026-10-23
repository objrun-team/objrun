"""16 worker scheduler around the unchanged frozen grader.fit and fit_worker."""
import os,threading
from http.server import ThreadingHTTPServer
from support import CONTROL,core,MeteredPool
import grader
grader.POOL.shutdown(wait=True);grader.POOL=MeteredPool(16,'parameter-fit')
class Handler(grader.Handler):
    def do_GET(self):
        if self.path=='/concurrency':self.reply(grader.POOL.metrics());return
        return super().do_GET()
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.environ['GRADER_PORT'])),Handler).serve_forever()
