const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const {request} = require('../client');
test('HTTP client preserves Unicode, authentication and API errors',async()=>{
  const server=http.createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');
    if(req.url==='/api/fail'){res.statusCode=409;res.end(JSON.stringify({error:'任务已结束'}));return;}
    assert.equal(req.headers.authorization,'Bearer test-token');
    let body='';req.setEncoding('utf8');req.on('data',s=>body+=s);
    req.on('end',()=>res.end(JSON.stringify({url:req.url,body:JSON.parse(body)})));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{
    const endpoint=`http://127.0.0.1:${server.address().port}/api`;
    assert.deepEqual(await request(endpoint,'/tasks','test-token',{description:'你好，修改代码'}),{url:'/api/tasks',body:{description:'你好，修改代码'}});
    await assert.rejects(request(endpoint,'/fail'),/任务已结束/);
  }finally{await new Promise(r=>server.close(r));}
});
