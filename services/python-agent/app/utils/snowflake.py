import time
import threading

class SnowflakeGenerator:
    # 雪花算法 自定义46位时间戳 5位机器id 12位序列号
    def __init__(self,worker_id: int = 2):
        self._worker_id = worker_id & 0x1F
        self._sequence = 0
        self._last_ts = -1
        self._lock = threading.Lock()
        self._epoch = 1609459200000
    def next_id(self)->int:
        with self._lock:
            ts = int(time.time() * 1000)
            if ts == self._last_ts:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    while ts <= self._last_ts:
                        ts = int(time.time() * 1000)
            else:
                self._sequence = 0
            self._last_ts = ts
            return ((ts - self._epoch) << 17) | (self._worker_id << 12) | self._sequence

snowflake = SnowflakeGenerator()