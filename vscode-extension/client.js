const http = require('node:http');
const https = require('node:https');
function request(endpoint, route, token, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(endpoint.replace(/\/$/, '') + route);
    if (!['http:', 'https:'].includes(url.protocol)) return reject(new Error('地址必须是 HTTP 或 HTTPS'));
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const req = (url.protocol === 'https:' ? https : http).request(url, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: {...(token ? {Authorization: `Bearer ${token}`} : {}), ...(payload ? {'Content-Type':'application/json','Content-Length':Buffer.byteLength(payload)} : {})}
    }, res => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { data += chunk; if (data.length > 16 * 1024 * 1024) req.destroy(new Error('响应过大，请减少查询范围')); });
      res.on('error', reject);
      res.on('end', () => {
        let value;
        try { value = JSON.parse(data); } catch { return reject(new Error(`引擎返回非 JSON 响应 (${res.statusCode})`)); }
        if (res.statusCode >= 400) return reject(new Error(value.error || `HTTP ${res.statusCode}`));
        resolve(value);
      });
    });
    const timer = setTimeout(() => req.destroy(new Error('连接超时，请检查引擎地址和启动日志')), 15000);
    req.on('close', () => clearTimeout(timer));
    req.on('error', reject);
    req.end(payload);
  });
}
module.exports = {request};
