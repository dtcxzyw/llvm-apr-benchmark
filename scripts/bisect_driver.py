#!/usr/bin/env python3
# Copyright 2025 Yingwei Zheng
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import sys
import llvm_helper
import json
import subprocess
import dateparser
from datetime import timezone

bisect_runner_file = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bisect_runner.py"
)


def is_llvm_functional_change(commit: str) -> bool:
    commit = commit.strip()
    changed_files = llvm_helper.git_execute(
        [
            "show",
            "--name-only",
            "--format=",
            commit,
            "--",
            "llvm/lib/*",
            "llvm/include/*",
        ]
    ).strip()
    return changed_files != ""


def bisect_issue(issue):
    path = os.path.join(llvm_helper.dataset_dir, issue)
    with open(path) as f:
        data = json.load(f)
    if data["bug_type"] == "hang":
        # Not supported yet
        return
    if "bisect" in data and data["bisect"] != "N/A":
        return
    print(data["issue"]["title"])
    try:
        base_commit = data["base_commit"]  # bad
        base_commit_time = dateparser.parse(
            llvm_helper.git_execute(["show", "-s", "--format=%ci", base_commit]).strip()
        ).astimezone(timezone.utc)
        report_time = dateparser.parse(data["knowledge_cutoff"]).astimezone(
            timezone.utc
        )
        print("Report time:", report_time)
        print("Base commit time:", base_commit_time)
        if report_time < base_commit_time:
            commit_before_report = llvm_helper.git_execute(
                [
                    "log",
                    "--before",
                    report_time.isoformat(),
                    "--oneline",
                    "-n",
                    "1",
                    "--no-abbrev",
                    "--format=%H",
                ]
            ).strip()
            if (
                base_commit != commit_before_report
                and subprocess.run(
                    [bisect_runner_file, path, commit_before_report]
                ).returncode
                == 1
            ):
                base_commit = commit_before_report
                print("Adjusted base commit to", base_commit)
            else:
                print("Use original base commit (unavailable)")
        else:
            print("Use original base commit (newer)")

        good_commit = None
        offset = 100
        while offset <= 204800:  # ~5 years
            commit_sha = llvm_helper.git_execute(
                ["rev-parse", f"{base_commit}~{offset}"]
            ).strip()
            if subprocess.run([bisect_runner_file, path, commit_sha]).returncode == 0:
                good_commit = commit_sha
                break
            offset = int(offset * 1.6)
        if good_commit is None:
            raise RuntimeError("Cannot find a good commit")
        print("BAD", base_commit, "GOOD", good_commit)
        llvm_helper.git_execute(["bisect", "reset"])
        llvm_helper.git_execute(
            ["bisect", "start", "--no-checkout", base_commit, good_commit]
        )
        out = subprocess.check_output(
            [
                "git",
                "-C",
                llvm_helper.llvm_dir,
                "bisect",
                "run",
                bisect_runner_file,
                path,
            ],
            cwd=llvm_helper.llvm_dir,
            timeout=600.0,
        ).decode()
        if not out.endswith("bisect found first bad commit\n"):
            raise RuntimeError("Bisect failed: " + out)
        pos = out.rfind(" is the first bad commit\n")
        if pos == -1:
            raise RuntimeError("Bisect failed")
        pos2 = out.rfind("\n", 0, pos)
        if pos2 == -1:
            raise RuntimeError("Bisect failed")
        first_bad = out[pos2 + 1 : pos].strip()
        print(first_bad)
        data["bisect"] = first_bad
    except subprocess.TimeoutExpired:
        data["bisect"] = "Timeout"
        print("Timeout")
    except subprocess.CalledProcessError as e:
        out = e.stdout.decode()
        key = "The first bad commit could be any of:\n"
        pos = out.rfind(key)
        if pos == -1:
            return
        pos2 = out.find("We cannot bisect more!", pos)
        if pos2 == -1:
            return
        candidates = out[pos + len(key) : pos2].strip().splitlines()
        if len(candidates) > 1:
            candidates = list(filter(is_llvm_functional_change, candidates))
        # TODO: filter by pass name (not component name!)
        if len(candidates) == 0:
            data["bisect"] = "Unrelated"
        elif len(candidates) == 1:
            first_bad = candidates[0].strip()
            print(first_bad)
            data["bisect"] = first_bad
    except Exception as e:
        data["bisect"] = str(e)
        print(e)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


task_list = []
if len(sys.argv) == 2:
    task_list = [sys.argv[1] + ".json"]
else:
    for name in os.listdir(llvm_helper.dataset_dir):
        if name.endswith(".json"):
            task_list.append(name)
task_list.sort(reverse=True)

for idx, task in enumerate(task_list):
    print("Bisecting", idx + 1, task.removesuffix(".json"))
    try:
        bisect_issue(task)
    except Exception as e:
        print(e)
        pass
