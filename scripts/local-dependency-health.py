"""Read-only MySQL/Redis readiness checks for the Windows launcher; never prints credentials."""
import asyncio
import os
from pathlib import Path

import aiomysql
from dotenv import load_dotenv
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "python-agent/.env.runtime.local")
load_dotenv(ROOT / "python-agent/.env")


def check_redis(prefix, default_port, modules=False):
    client = Redis(host=os.getenv(prefix + "HOST", "localhost"),
                   port=int(os.getenv(prefix + "PORT", str(default_port))),
                   db=int(os.getenv(prefix + "DB", "0")),
                   password=os.getenv(prefix + "PASSWORD") or None,
                   socket_timeout=5, socket_connect_timeout=5, decode_responses=True)
    try:
        if not client.ping():
            raise RuntimeError("Redis PING failed")
        if modules:
            loaded = {item["name"].lower() for item in client.module_list()}
            if not {"search", "rejson"}.issubset(loaded):
                raise RuntimeError("Checkpoint Redis requires RediSearch and RedisJSON; ordinary Windows Redis is insufficient")
    finally:
        client.close()


async def check_mysql():
    connection = await aiomysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"), port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASSWORD", ""),
        db=os.getenv("MYSQL_DB", "easyjob"), connect_timeout=5)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            assert (await cursor.fetchone())[0] == 1
    finally:
        connection.close()


def main():
    for name, operation in [("MySQL", lambda: asyncio.run(check_mysql())),
                            ("Cache Redis", lambda: check_redis("REDIS_", 6379)),
                            ("Checkpoint Redis", lambda: check_redis("REDIS_STACK_", 6380, modules=True))]:
        try:
            operation()
            print(name + " ready")
        except Exception as error:
            print(f"{name} readiness failed ({type(error).__name__}); check local connection settings and service logs.")
            # Connector exceptions may include credentials or connection URLs.
            if isinstance(error, RuntimeError):
                print(str(error))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
