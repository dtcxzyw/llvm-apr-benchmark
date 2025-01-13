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

import llvm_helper
import json
import os
import dateparser
import time
import re
from typing import Tuple, Sequence


class TimeCompensationGuard:
    def __init__(self, environment):
        self.environment = environment

    def __enter__(self):
        self.start_time = time.time()
        self.environment.interaction_time_compensation_enter += 1

    def __exit__(self):
        self.environment.interaction_time_compensation_enter -= 1
        if self.environment.interaction_time_compensation_enter == 0:
            self.environment.interaction_time_compensation += (
                time.time() - self.start_time
            )


class Environment:
    def __init__(
        self,
        issue_id,
        base_model_knowledge_cutoff: str,
        *,
        additional_knowledge_list: Sequence[Tuple[str, str]] = [],
        max_build_jobs=None,
    ):
        with open(os.path.join(llvm_helper.dataset_dir, f"{issue_id}.json")) as f:
            self.data = json.load(f)
        self.base_commit = self.data["base_commit"]
        self.knowledge_cutoff = dateparser.parse(self.data["knowledge_cutoff"])
        self.used_knowledge = dict()
        self.use_knowledge("base_model", base_model_knowledge_cutoff)
        for k, v in additional_knowledge_list:
            self.use_knowledge(k, v)
        self.interaction_time_compensation = 0.0
        self.interaction_time_compensation_enter = 0
        self.fast_check_count = 0
        self.full_check_count = 0
        self.fast_check_pass = False
        self.full_check_pass = False
        if max_build_jobs is None:
            self.max_build_jobs = os.cpu_count()
        else:
            self.max_build_jobs = max_build_jobs
        self.start_time = time.time()

    def use_knowledge(self, url: str, date: str):
        date = dateparser.parse(date)
        if date <= self.knowledge_cutoff:
            self.used_knowledge[url] = min(self.used_knowledge.get(url, date), date)
        else:
            raise ValueError("Knowledge is newer than the cutoff date")

    def reset(self):
        with TimeCompensationGuard(self):
            llvm_helper.reset(self.base_commit)

    def verify_head(self):
        head = llvm_helper.git_execute(["rev-parse", "HEAD"])
        if head != self.data["base_commit"]:
            raise RuntimeError("invalid HEAD")

    def build(self):
        with TimeCompensationGuard(self):
            self.verify_head()
            return llvm_helper.build(self.max_build_jobs)

    def dump(self):
        wall_time = time.time() - self.start_time - self.interaction_time_compensation
        self.verify_head()
        patch = llvm_helper.git_execute(["diff", "--", "llvm/lib/*", "llvm/include/*"])
        return {
            "wall_time": wall_time,
            "knowledge": self.used_knowledge,
            "fast_check_count": self.fast_check_count,
            "full_check_count": self.full_check_count,
            "fast_check_pass": self.fast_check_pass,
            "full_check_pass": self.full_check_pass,
            "patch": patch,
        }

    def check_fast(self):
        with TimeCompensationGuard(self):
            self.fast_check_count += 1
            res, reason = self.build()
            if not res:
                return (False, reason)
            # TODO
            return (True, "")

    def check_full(self):
        with TimeCompensationGuard(self):
            self.full_check_count += 1
            res, reason = self.build()
            if not res:
                return (False, reason)
            # TODO
            return (True, "")

    def get_bug_type(self):
        return self.data["bug_type"]

    def get_tests(self):
        return self.data["tests"]

    def get_hint_fix_commit(self):
        self.use_knowledge("hint:fix_commit", self.knowledge_cutoff)
        return self.data["hints"]["fix_commit"]

    def get_hint_components(self):
        self.use_knowledge("hint:components", self.knowledge_cutoff)
        return self.data["hints"]["components"]

    def get_hint_files(self):
        self.use_knowledge("hint:files", self.knowledge_cutoff)
        return self.data["hints"]["files"]

    def get_hint_bug_functions(self):
        self.use_knowledge("hint:bug_functions", self.knowledge_cutoff)
        return self.data["hints"]["bug_location_funcname"]

    def get_hint_line_level_bug_locations(self):
        self.use_knowledge("hint:line_level_bug_locations", self.knowledge_cutoff)
        return self.data["hints"]["bug_location_lineno"]

    def get_hint_issue(self):
        self.use_knowledge("hint:issue", self.knowledge_cutoff)
        return self.data["issue"]

    def get_ir_keywords(self, ir: str):
        keywords = set()
        # instructions
        instruction_pattern = re.compile(r"%.+ = (\w+) ")
        for match in re.findall(instruction_pattern, ir):
            keywords.add(match)
        # intrinsics
        intrinsic_pattern = re.compile(r"@(llvm.\w+)\(")
        for match in re.findall(intrinsic_pattern, ir):
            keywords.add(match)
        keywords.discard("call")
        return keywords

    def get_langref_desc(self, keywords):
        self.use_knowledge("llvm/docs/LangRef.rst", self.knowledge_cutoff)
        return llvm_helper.get_langref_desc(keywords, self.base_commit)
