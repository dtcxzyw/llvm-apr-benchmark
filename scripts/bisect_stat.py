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
import subprocess
import llvm_helper
import json
import dateparser
from datetime import timezone
import math
from unidiff import PatchSet
import string
import matplotlib.pyplot as plt

total = 0
available_count = 0
report_to_fix_record = []
bug_to_fix_record = []
bug_to_report_record = []
related_count_file_level = 0
related_count_line_level = 0


def geomean(nums):
    log_sum = sum([math.log(x) for x in nums])
    return math.exp(log_sum / len(nums))


def analyze_patch(patch: str) -> dict:
    lines = dict()
    patch_set = PatchSet(patch)
    special_chars = set(string.punctuation + string.whitespace)
    for patched_file in patch_set:
        filename = patched_file.path
        file_lines = set()
        for hunk in patched_file:
            for line in hunk:
                canonicalized = line.value.strip()
                canonicalized = "".join(
                    [" " if c in special_chars else c for c in canonicalized]
                )
                if len(canonicalized) < 16:
                    continue
                file_lines.add(canonicalized)
        lines[filename] = file_lines
    return lines


for name in os.listdir(llvm_helper.dataset_dir):
    if not name.endswith(".json"):
        continue
    total += 1
    path = os.path.join(llvm_helper.dataset_dir, name)
    with open(path) as f:
        data = json.load(f)
    if "bisect" not in data:
        continue
    run = subprocess.run(
        ["git", "-C", llvm_helper.llvm_dir, "rev-parse", data["bisect"]],
        capture_output=True,
    )
    if run.returncode != 0:
        continue
    if run.stdout.decode().strip() != data["bisect"]:
        continue
    report_time = dateparser.parse(data["knowledge_cutoff"]).astimezone(timezone.utc)
    bug_time = dateparser.parse(
        llvm_helper.git_execute(["show", "-s", "--format=%ci", data["bisect"]]).strip()
    ).astimezone(timezone.utc)
    fix_commit = data["hints"]["fix_commit"]
    fix_time = dateparser.parse(
        llvm_helper.git_execute(["show", "-s", "--format=%ci", fix_commit]).strip()
    ).astimezone(timezone.utc)
    bug_commit_title = llvm_helper.git_execute(
        ["show", "-s", "--format=%s", data["bisect"]]
    ).strip()
    fix_commit_title = llvm_helper.git_execute(
        ["show", "-s", "--format=%s", fix_commit]
    ).strip()
    print(bug_commit_title, "->", fix_commit_title)
    report_to_fix = (fix_time - report_time).total_seconds() / 86400
    bug_to_fix = (fix_time - bug_time).total_seconds() / 86400
    bug_to_report = (report_time - bug_time).total_seconds() / 86400
    if report_to_fix < 0 or bug_to_fix < 0 or bug_to_report < 0:
        print("Invalid time data, skip")
        print(f"  report time: {report_time}")
        print(f"  bug time: {bug_time}")
        print(f"  fix time: {fix_time}")
        with open(path, "w") as f:
            data["bisect"] = "Invalid order"
            json.dump(data, f, indent=2)
        continue
    available_count += 1
    report_to_fix_record.append(report_to_fix)
    bug_to_fix_record.append(bug_to_fix)
    bug_to_report_record.append(bug_to_report)

    fix_lines = analyze_patch(data["patch"])
    buggy_patch = llvm_helper.git_execute(["show", data["bisect"], "--", "llvm/lib/*", "llvm/include/*"])
    buggy_lines = analyze_patch(buggy_patch)
    is_related_file_level = False
    is_related_line_level = False
    for filename, lines in fix_lines.items():
        if filename in buggy_lines:
            is_related_file_level = True
            if len(lines.intersection(buggy_lines[filename])) > 0:
                is_related_line_level = True
    if is_related_file_level:
        related_count_file_level += 1
    if is_related_line_level:
        related_count_line_level += 1
print(
    f"Available bisect result: {available_count}/{total} ({available_count/total*100:.2f}%)"
)
print(f"Average report to fix: {geomean(report_to_fix_record):.2f} days")
print(f"Average bug to fix: {geomean(bug_to_fix_record):.2f} days")
print(f"Average bug to report: {geomean(bug_to_report_record):.2f} days")
print(
    f"p95 bug to report: {sorted(bug_to_report_record)[int(len(bug_to_report_record)*0.95)]:.2f} days"
)
print(f"Bisection precision (file level): {related_count_file_level}/{available_count} ({related_count_file_level/available_count*100:.2f}%)")
print(f"Bisection precision (line level): {related_count_line_level}/{available_count} ({related_count_line_level/available_count*100:.2f}%)")

fig = plt.figure(figsize=(9, 4), layout="constrained")
axs = fig.subplots(1, 3)
data_lists = {
    "Report to fix": report_to_fix_record,
    "Bug to fix": bug_to_fix_record,
    "Bug to report": bug_to_report_record,
}
for ax, (title, data) in zip(axs, data_lists.items()):
    ax2 = ax.twinx()
    ax.hist(data, bins=30)
    ax2.ecdf(data, color="orange")
    ax.set_title(title)
    ax.set_ylabel("Count")
    ax2.set_ylabel("Probability of occurrence")
    ax.set_xlabel("Duration (day)")
    ax.grid(True)
fig.savefig("work/bisect_stat.png", dpi=300)
plt.close(fig)
