"""Run interaction regression tests; --mysql adds real local InnoDB concurrency checks.

Use python-agent/.venv/Scripts/python.exe scripts/test-article-interactions.py --mysql.
Credentials are read from local environment files and passed as process environment only.
MySQL tests create/drop a random easyjob_interaction_test_* database, never the application DB.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / "python-agent/.env.runtime.local")
    load_dotenv(root / "python-agent/.env")
    env = os.environ.copy()
    env.pop("EASYJOB_INTERACTION_DB_TEST", None)
    if args.mysql:
        if env.get("MYSQL_HOST", "localhost") not in {"localhost", "127.0.0.1", "::1"}:
            parser.error("--mysql only permits a local/disposable MySQL instance")
        env["EASYJOB_INTERACTION_DB_TEST"] = "1"
    if os.name == "nt" and Path("D:/jdk").is_dir():
        env["JAVA_HOME"] = "D:/jdk"
    maven = shutil.which("mvn") or shutil.which("mvn.cmd")
    if not maven:
        bundled = Path("D:/IntelliJ IDEA Community Edition 2025.1.3/plugins/maven/lib/maven3/bin/mvn.cmd")
        if bundled.is_file():
            maven = str(bundled)
    if not maven:
        parser.error("Maven not found; add mvn to PATH")
    tests = ["ArticleInteractionTests", "ArticleChunkIndexTests", "InteractionProjectionTests",
             "NotificationTests", "ArticleLifecycleTests", "PersistenceLayerTests"]
    if args.mysql:
        tests.append("ArticleInteractionMysqlTests")
    log = root / "temp/article-interaction-check.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run([maven, "-q", "-Deasyjob.build.directory=target/interaction-validated",
                                 "-Dtest=" + ",".join(tests), "test"],
                                cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        print(f"Interaction regression failed; inspect {log}")
        return result.returncode
    totals = {key: 0 for key in ["tests", "failures", "errors", "skipped"]}
    reports = root / "target/interaction-validated/surefire-reports"
    for test in tests:
        matches = list(reports.glob("TEST-*." + test + ".xml"))
        if len(matches) != 1:
            raise RuntimeError("Missing or ambiguous test report: " + test)
        suite = ET.parse(matches[0]).getroot()
        for key in totals:
            totals[key] += int(suite.get(key, "0"))
    print("Interaction regression passed: " + ", ".join(f"{key}={value}" for key, value in totals.items()))
    if args.mysql:
        print("Real MySQL concurrency and transaction rollback verified in an isolated temporary database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
