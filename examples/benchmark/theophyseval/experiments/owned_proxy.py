"""Proxy only the experiment's container subnet to its owned approved SSH exit."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

SUBNET=ipaddress.ip_network('172.29.240.0/20')

async def pump(reader,writer):
    try:
        while True:
            data=await reader.read(65536)
            if not data:break
            writer.write(data);await writer.drain()
    finally:writer.close()

async def client(reader,writer):
    try:
        if ipaddress.ip_address(writer.get_extra_info('peername')[0]) not in SUBNET:
            return
        header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),15)
        method,target,_=header.split(b'\r\n',1)[0].decode('ascii').split(' ',2)
        host=urlsplit('//'+target if method=='CONNECT' else target).hostname
        if not host or host.lower()=='localhost':raise ValueError('Private destination')
        infos=await asyncio.get_running_loop().getaddrinfo(host,None,type=socket.SOCK_STREAM)
        if not infos or any(not ipaddress.ip_address(x[4][0]).is_global for x in infos):
            raise ValueError('Private destination')
        upstream,upwriter=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',18493),10)
        upwriter.write(header);await upwriter.drain()
        await asyncio.gather(pump(reader,upwriter),pump(upstream,writer))
    except Exception:
        writer.write(b'HTTP/1.1 403 Proxy destination unavailable\r\nConnection: close\r\n\r\n')
    finally:writer.close()

async def main():
    server=await asyncio.start_server(client,'172.29.240.1',18494)
    async with server:await server.serve_forever()

if __name__=='__main__':asyncio.run(main())
