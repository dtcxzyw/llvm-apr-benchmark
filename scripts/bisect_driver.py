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
import bisect_runner
import subprocess

bisect_runner_file = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bisect_runner.py"
)


def bisect_issue(issue):
    path = os.path.join(llvm_helper.dataset_dir, issue)
    with open(path) as f:
        data = json.load(f)
    if "bisect" in data:
        return
    print(data["issue"]["title"])
    base_commit = data["base_commit"]  # bad
    good_commit = None
    offset = 100
    while offset <= 204800:  # ~5 years
        commit_sha = llvm_helper.git_execute(
            ["rev-parse", f"{base_commit}~{offset}"]
        ).strip()
        if bisect_runner.test(commit_sha, path) == 0:
            good_commit = commit_sha
            break
        offset = int(offset * 1.6)
    if good_commit is None:
        print("Cannot find a good commit")
        return
    print("BAD", base_commit, "GOOD", good_commit)
    llvm_helper.git_execute(["bisect", "reset"])
    llvm_helper.git_execute(
        ["bisect", "start", "--no-checkout", base_commit, good_commit]
    )
    out = subprocess.check_output(
        ["git", "-C", llvm_helper.llvm_dir, "bisect", "run", bisect_runner_file, path],
        cwd=llvm_helper.llvm_dir,
    ).decode()
    if not out.endswith("bisect found first bad commit\n"):
        return
    pos = out.rfind(" is the first bad commit\n")
    if pos == -1:
        return
    pos2 = out.rfind("\n", 0, pos)
    if pos2 == -1:
        return
    first_bad = out[pos2 + 1 : pos].strip()
    print(first_bad)
    data["bisect"] = first_bad
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


task_list = []
if len(sys.argv) == 2:
    task_list = [sys.argv[1] + ".json"]
else:
    for name in os.listdir(llvm_helper.dataset_dir):
        if name.endswith(".json"):
            task_list.append(name)
task_list.sort()

for idx, task in enumerate(task_list):
    print("Bisecting", idx + 1, task.removesuffix(".json"))
    try:
        bisect_issue(task)
    except Exception as e:
        print(e)
        pass
