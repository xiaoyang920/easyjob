"""Exercise Blog Outbox, RabbitMQ, the index worker, and Elasticsearch in disposable CI."""
import argparse
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pymysql

ELASTICSEARCH = os.getenv("SEARCH_INDEX_SMOKE_ES_URL", "http://127.0.0.1:9200")
WORKER = os.getenv("SEARCH_INDEX_SMOKE_WORKER_URL", "http://127.0.0.1:8084")


class EmbeddingFixture(BaseHTTPRequestHandler):
    def request_body(self):
        if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
            return self.rfile.read(int(self.headers["Content-Length"]))
        chunks = []
        while size := int(self.rfile.readline().split(b";", 1)[0], 16):
            chunks.append(self.rfile.read(size))
            self.rfile.read(2)
        while self.rfile.readline() not in (b"\r\n", b""):
            pass
        return b"".join(chunks)

    def do_POST(self):
        if self.path != "/v4/embeddings":
            self.send_error(404)
            return
        request = json.loads(self.request_body())
        inputs = request["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        response = json.dumps({
            "object": "list",
            "model": request["model"],
            "data": [{"object": "embedding", "index": index, "embedding": [1.0] + [0.0] * 2047}
                     for index in range(len(inputs))],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def get(url):
    try:
        with urlopen(url, timeout=3) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def wait_for(description, check, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {description}")


def enqueue(cursor, article_id, action, route):
    job_id = str(uuid.uuid4())
    cursor.execute(
        """INSERT INTO article_index_outbox(job_id, article_id, action, routing_key, available_at, created_at, updated_at)
           VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))""",
        (job_id, article_id, action, route),
    )
    return job_id


def completed(cursor, job_id):
    cursor.execute("SELECT status FROM article_index_outbox WHERE job_id=%s", (job_id,))
    status = cursor.fetchone()[0]
    if status == "dead":
        raise RuntimeError(f"Index job {job_id} exhausted retries")
    return status == "completed"


def vector_count(article_id):
    result = get(f"{ELASTICSEARCH}/article_vectors/_count?q=article_id:{article_id}")
    return result["count"]


def smoke():
    database = os.environ["MYSQL_DB"]
    if os.getenv("EASYJOB_CI") != "1" or not database.endswith("_ci"):
        raise SystemExit("This smoke check requires a disposable *_ci database")
    wait_for("index service", lambda: (get(f"{WORKER}/actuator/health") or {}).get("status") == "UP")
    article_id = 2**60 + int.from_bytes(os.urandom(5), "big")
    document_url = f"{ELASTICSEARCH}/article/_doc/{article_id}"
    with pymysql.connect(host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")),
                         user=os.environ["MYSQL_USER"],
                         password=os.environ["MYSQL_PASSWORD"], database=database, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO article_info(article_id,user_id,title,content,status,deleted,required_level,
                                            publish_time,create_time,update_time,data_source)
                   VALUES (%s,7,'Index fixture','<p>Unique index integration paragraph</p>',1,0,0,
                           NOW(),NOW(),NOW(),'evaluation')""",
                (article_id,),
            )
            job_id = enqueue(cursor, article_id, "PUBLISH", "article.publish")
            connection.commit()
            connection.autocommit(True)
            try:
                wait_for("published job acknowledgement", lambda: completed(cursor, job_id))
                assert get(document_url)["_source"]["title"] == "Index fixture"
                wait_for("article vector", lambda: vector_count(article_id) > 0)

                connection.autocommit(False)
                cursor.execute("UPDATE article_info SET title=%s WHERE article_id=%s", ("Edited fixture", article_id))
                update_job = enqueue(cursor, article_id, "UPDATE", "article.update")
                connection.commit()
                connection.autocommit(True)
                wait_for("edit job acknowledgement", lambda: completed(cursor, update_job))
                assert get(document_url)["_source"]["title"] == "Edited fixture"

                connection.autocommit(False)
                cursor.execute("UPDATE article_info SET status=2 WHERE article_id=%s", (article_id,))
                delete_job = enqueue(cursor, article_id, "DELETE", "article.delete")
                connection.commit()
                connection.autocommit(True)
                wait_for("unpublish job acknowledgement", lambda: completed(cursor, delete_job))
                assert get(document_url) is None
                wait_for("vector removal", lambda: vector_count(article_id) == 0)
            finally:
                connection.rollback()
                connection.autocommit(True)
                cursor.execute("DELETE FROM article_index_outbox WHERE article_id=%s", (article_id,))
                cursor.execute("DELETE FROM article_info WHERE article_id=%s", (article_id,))
    print("Article publish, edit and unpublish passed across Blog, RabbitMQ and Search Index.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedding-fixture", action="store_true")
    if parser.parse_args().embedding_fixture:
        with ThreadingHTTPServer(("127.0.0.1", 18084), EmbeddingFixture) as server:
            server.serve_forever()
    else:
        smoke()
