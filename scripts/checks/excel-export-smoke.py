"""Submit, poll, download and validate a community statistics export through the public API."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from getpass import getpass
from io import BytesIO
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile


JOBS = "/api/admin/statistics/export-jobs"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = ["日期", "新增用户", "首次发布文章", "有效阅读秒数", "有效阅读用户数"]


def call(base_url, path, token=None, payload=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base_url + path, headers=headers,
                      data=None if payload is None else json.dumps(payload).encode())
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def unwrap(response):
    status, _, body = response
    result = json.loads(body)
    if status != 200 or result.get("code") != 200:
        raise ValueError(f"HTTP {status}, API {result.get('code')}: {result.get('message')}")
    return result["data"]


def verify_workbook(content, start, days):
    with ZipFile(BytesIO(content)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        names = [sheet.attrib["name"] for sheet in workbook.findall("s:sheets/s:sheet", NS)]
        if names != ["每日统计"]:
            raise ValueError(f"Unexpected worksheets: {names}")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(node.itertext()) for node in shared.findall("s:si", NS)]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = sheet.findall("s:sheetData/s:row", NS)

        def cell_value(cell):
            value = cell.findtext("s:v", default="", namespaces=NS)
            if cell.get("t") == "s":
                return strings[int(value)]
            if cell.get("t") == "inlineStr":
                return "".join(cell.find("s:is", NS).itertext())
            return value

        if len(rows) != days + 1 or [cell_value(cell) for cell in rows[0]] != HEADERS:
            raise ValueError("Workbook row count or headers are incorrect")
        for index, row in enumerate(rows[1:]):
            cells = row.findall("s:c", NS)
            expected = (start + timedelta(days=index)).isoformat()
            if len(cells) != 5 or cell_value(cells[0]) != expected:
                raise ValueError(f"Expected date {expected} on row {index + 2}")
            if any(cell.get("t", "n") != "n" or float(cell_value(cell)) < 0 for cell in cells[1:]):
                raise ValueError(f"Invalid numeric value for {expected}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--email", help="Administrator email. Prompts for password unless EXCEL_ADMIN_TOKEN is set.")
    parser.add_argument("--days", type=int, choices=(7, 30, 90), default=30)
    parser.add_argument("--source", choices=("business", "evaluation", "all"), default="business")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    token = os.getenv("EXCEL_ADMIN_TOKEN")
    if not token:
        if not args.email:
            parser.error("Pass --email or set EXCEL_ADMIN_TOKEN")
        token = unwrap(call(base, "/api/auth/login", payload={
            "email": args.email, "password": getpass("Admin password: "),
        }))["token"]

    payload = {"requestId": str(uuid4()), "days": args.days, "source": args.source}
    with ThreadPoolExecutor(max_workers=2) as pool:
        submissions = list(pool.map(lambda _: unwrap(call(base, JOBS, token, payload)), range(2)))
    job = submissions[0]
    job_no = str(UUID(job["jobNo"]))
    if job_no != submissions[1]["jobNo"]:
        raise ValueError("Submitting the same request ID created multiple jobs")

    job_path = f"{JOBS}/{job_no}"
    deadline = time.monotonic() + args.timeout
    while job["status"] in ("pending", "running") and time.monotonic() < deadline:
        time.sleep(1.5)
        job = unwrap(call(base, job_path, token))
    if job["status"] != "succeeded" or job["rowCount"] != args.days or job["source"] != args.source:
        raise ValueError(f"Unexpected final status for {job_no}: {job}")
    start = date.fromisoformat(job["from"])
    if date.fromisoformat(job["to"]) != start + timedelta(days=args.days - 1):
        raise ValueError("Incorrect exported date range")

    unauthorized, headers, body = call(base, job_path + "/file")
    if unauthorized not in (401, 403):
        # Some deployments report authorization failures using the API envelope.
        if unauthorized != 200 or "json" not in headers.get("Content-Type", "") \
                or json.loads(body).get("code") not in (401, 403):
            raise ValueError(f"Expected the anonymous download to be denied, got HTTP {unauthorized}")
    status, headers, content = call(base, job_path + "/file", token)
    if status != 200 or "spreadsheetml.sheet" not in headers.get("Content-Type", ""):
        raise ValueError(f"Unexpected file response HTTP {status}")
    verify_workbook(content, start, args.days)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as output:
            output.write(content)
    print(f"OK {job_no} {args.source} {job['from']}..{job['to']}, {args.days} rows, one worksheet")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(f"Excel export check failed: {error}")
