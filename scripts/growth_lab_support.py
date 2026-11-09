"""Isolated lab support: TCP fault proxy and Windows process counters. No product hooks."""
import asyncio, ctypes, os, time, json, socket, subprocess, sys, secrets
from ctypes import wintypes


class FaultProxy:
    def __init__(self, target):
        self.target=target;self.mode='normal';self.writers=set();self.server=None
    async def start(self):
        self.server=await asyncio.start_server(self.handle,'127.0.0.1',0)
        return self.server.sockets[0].getsockname()[1]
    async def handle(self, reader, writer):
        if self.mode=='cut':writer.close();return
        try:
            upstream, destination=await asyncio.open_connection('127.0.0.1',self.target)
        except OSError:writer.close();return
        self.writers.update((writer,destination))
        async def pipe(source,sink,downstream=False):
            try:
                while data:=await source.read(65536):
                    if downstream and self.mode=='drop_confirm':continue
                    sink.write(data);await sink.drain()
            except (OSError,asyncio.CancelledError):pass
            finally:sink.close()
        try:await asyncio.gather(pipe(reader,destination),pipe(upstream,writer,True))
        finally:
            for connection in (writer,destination):connection.close();self.writers.discard(connection)
    def mode_set(self, mode):
        self.mode=mode
        if mode in ('cut','normal'):
            for writer in list(self.writers):writer.close()
    async def close(self):
        self.mode_set('cut');self.server.close();await self.server.wait_closed()


class RemoteProxy:
    def __init__(self,target,folder,name):
        self.target=target;self.folder=folder;self.name=name;self.token=secrets.token_urlsafe(32);self.process=None
    async def start(self):
        from pathlib import Path
        ready=self.folder/(self.name+'-ready.json');config=self.folder/(self.name+'-control.json')
        config.write_text(json.dumps({'target':self.target,'ready':str(ready),'token':self.token}))
        # Windows venv python.exe is a launcher with a second Python process.
        # This helper only needs stdlib: start the actual interpreter so PID stats
        # and termination refer to the server itself, without an orphaned child.
        interpreter=getattr(sys,'_base_executable',sys.executable)
        self.process=subprocess.Popen([interpreter,str(Path(__file__).with_name('growth_lab_proxy.py')),str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if ready.exists():
                self.address=json.loads(ready.read_text());return self.address['port']
            if self.process.poll() is not None:break
            await asyncio.sleep(.05)
        raise RuntimeError('Dedicated fault proxy did not start')
    def mode_set(self,mode):
        with socket.create_connection(('127.0.0.1',self.address['control']),timeout=3) as connection:
            connection.sendall((json.dumps({'token':self.token,'mode':mode})+'\n').encode())
            if connection.recv(16)!=b'OK\n':raise RuntimeError('Fault proxy control failed')
    async def close(self):
        if self.process and self.process.poll() is None:self.process.terminate();await asyncio.to_thread(self.process.wait,5)
        (self.folder/(self.name+'-control.json')).unlink(missing_ok=True)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(key,ctypes.c_size_t) for key in
        ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]


def process_sample(pid):
    if os.name!='nt':return {}
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    handle=kernel.OpenProcess(0x0400|0x0010,False,pid)
    if not handle:return {}
    try:
        counters=PROCESS_MEMORY_COUNTERS();counters.cb=ctypes.sizeof(counters)
        psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(PROCESS_MEMORY_COUNTERS),wintypes.DWORD]
        psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),ctypes.sizeof(counters))
        times=[wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes(handle,*[ctypes.byref(item) for item in times])
        ticks=sum((item.dwHighDateTime<<32)|item.dwLowDateTime for item in times[2:])
        return {'cpu_seconds':ticks/1e7,'rss_mb':round(counters.WorkingSetSize/1048576,2),'private_mb':round(counters.PagefileUsage/1048576,2)}
    finally:kernel.CloseHandle(handle)


def percentiles(values):
    ordered=sorted(values)
    def at(p):return round(ordered[min(len(ordered)-1,int((len(ordered)-1)*p))],2) if ordered else None
    return {'p50_ms':at(.50),'p95_ms':at(.95),'p99_ms':at(.99),'max_ms':at(1)}
