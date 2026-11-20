"""Dedicated loopback TCP fault proxy: separate event loop from the load generator."""
import asyncio,json,sys
from pathlib import Path
from growth_lab_support import FaultProxy

async def main():
    config=json.loads(Path(sys.argv[1]).read_text())
    proxy=FaultProxy(config['target']);port=await proxy.start()
    async def control(reader,writer):
        try:
            command=json.loads(await asyncio.wait_for(reader.readline(),2))
            if command.get('token')!=config['token']:return
            if command.get('mode') not in ('normal','cut','drop_confirm'):return
            proxy.mode_set(command['mode']);writer.write(b'OK\n');await writer.drain()
        finally:writer.close()
    server=await asyncio.start_server(control,'127.0.0.1',0)
    Path(config['ready']).write_text(json.dumps({'port':port,'control':server.sockets[0].getsockname()[1]}))
    async with server:await server.serve_forever()

if __name__=='__main__':asyncio.run(main())
