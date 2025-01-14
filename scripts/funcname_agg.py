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
import llvm_helper
import json

funcnames = dict()
task_list = []
for name in os.listdir(llvm_helper.dataset_dir):
    if name.endswith(".json"):
        path = os.path.join(llvm_helper.dataset_dir, name)
        with open(path) as f:
            data = json.load(f)
            funcname = data["hints"]["bug_location_funcname"]
            for k, v in funcname.items():
                for key in v:
                    if "::" in key:
                        continue
                    if not llvm_helper.is_interesting_funcname(key):
                        continue
                    funcnames[key] = funcnames.get(key, 0) + 1

dist = sorted(funcnames.items(), key=lambda x: x[1], reverse=True)
for k, v in dist:
    print(k, v)
