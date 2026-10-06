"""Audited Linux regression shards; each process owns its GUI and test databases."""

import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

from ci_support import evidence


def canonical(item):
    node = item["nodeid"]
    known = (
        "test_paging_uses_username_or_uuid_and_checks_the_page_after_exact_limit",
        "test_count_presenter_never_accepts_mismatched_post_ack",
        "test_reversal_presenter_rejects_mismatched_ack",
    )
    if any(name in node for name in known):
        node = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", "<uuid4>", node)
    return (node, item["integration"], item["gui"])


def tests(env, options, pg_version=None):
    report = options.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    expected = report.with_suffix(".expected.json")
    env = {**env, "WMS_TEST_COLLECTION_REPORT": str(expected), "WMS_TEST_SUITE": "all"}
    paths = [str(p) for p in (options.test_path or ["tests"])]
    collect = subprocess.run(
        [sys.executable, "-m", "pytest", *paths, "--collect-only", "-q"],
        env=env,
        capture_output=True,
        text=True,
    )
    if collect.returncode:
        print(collect.stdout, collect.stderr)
        return 1
    selected = json.loads(expected.read_text())["selected"]
    groups = [[] for _ in range(options.jobs)]
    loads = [0] * options.jobs
    counts = Counter(x["nodeid"].split("::")[0] for x in selected)
    for file, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        idx = loads.index(min(loads))
        groups[idx].append(file)
        loads[idx] += count

    def shard(i, files):
        stem = report.parent / (report.stem + f"-shard{i}")
        childenv = {
            **env,
            "WMS_TEST_COLLECTION_REPORT": str(stem.with_suffix(".collection.json")),
            "WMS_TEST_SUITE": "shard",
        }
        for suffix in (".xml", ".collection.json"):
            stem.with_suffix(suffix).unlink(missing_ok=True)
        args = [
            "xvfb-run",
            "-a",
            sys.executable,
            "-m",
            "pytest",
            *files,
            "-q",
            "--tb=short",
            "--strict-markers",
            f"--junitxml={stem.with_suffix('.xml')}",
        ]
        with stem.with_suffix(".log").open("w") as log:
            result = subprocess.run(args, env=childenv, stdout=log, stderr=subprocess.STDOUT)
        print(f"shard {i}: exit {result.returncode}", flush=True)
        return (i, result.returncode, stem)

    outcomes = []
    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        for future in as_completed([pool.submit(shard, i, g) for i, g in enumerate(groups) if g]):
            outcomes.append(future.result())
    combined = ET.Element("testsuites")
    actual = []
    status = 0
    for i, code, stem in sorted(outcomes):
        status = max(status, code)
        if not stem.with_suffix(".xml").exists() or not stem.with_suffix(".collection.json").exists():
            status = 1
            continue
        for suite in ET.parse(stem.with_suffix(".xml")).getroot():
            combined.append(suite)
        actual += json.loads(stem.with_suffix(".collection.json").read_text())["selected"]
    ET.ElementTree(combined).write(report, encoding="utf-8", xml_declaration=True)
    expected_counter = Counter(map(canonical, selected))
    actual_counter = Counter(map(canonical, actual))
    coverage = expected_counter == actual_counter
    counts = {k: sum(int(s.get(k, 0)) for s in combined) for k in ("tests", "failures", "errors", "skipped")}
    if not coverage or any(counts[k] for k in ("failures", "errors", "skipped")):
        status = 1
    audit = dict(
        coverage=coverage,
        expected_nodes=len(selected),
        actual_nodes=len(actual),
        normalization="UUIDv4 labels only in 3 existing parametrized presenter tests",
        missing=list((expected_counter - actual_counter).elements()),
        extra=list((actual_counter - expected_counter).elements()),
    )
    report.with_suffix(".coverage.json").write_text(json.dumps(audit, indent=2) + "\n")
    evidence(
        report.with_suffix(".environment.json"),
        suite="all",
        gui=True,
        postgres=pg_version,
        result=status,
        junit=counts,
        coverage=audit,
        parallel_processes=options.jobs,
        test_paths=paths,
    )
    print(json.dumps(dict(result=status, junit=counts, coverage=coverage, nodes=len(actual))), flush=True)
    return status
