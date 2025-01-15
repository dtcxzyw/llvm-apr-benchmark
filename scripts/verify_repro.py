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

max_build_jobs = os.cpu_count()
max_build_jobs = 8


def verify_issue(issue):
    path = os.path.join(llvm_helper.dataset_dir, issue)
    with open(path) as f:
        data = json.load(f)
    if data.get("verified", False):
        return
    print(data["issue"]["title"])
    base_commit = data["base_commit"]
    llvm_helper.reset(base_commit)
    res, log = llvm_helper.build(max_build_jobs)
    if not res:
        print(log)
        return
    bug_type = data["bug_type"]
    res, log = llvm_helper.verify_test_group(
        repro=True, input=data["tests"], type=bug_type
    )
    if not res:
        print(log)
        return
    llvm_helper.apply(data["patch"])
    res, log = llvm_helper.build(max_build_jobs)
    if not res:
        print(log)
        return
    res, log = llvm_helper.verify_test_group(
        repro=False, input=data["tests"], type=bug_type
    )
    if not res:
        print(log)
        return
    data["verified"] = True

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
    print("Verifying", idx + 1, task.removesuffix(".json"))
    verify_issue(task)
