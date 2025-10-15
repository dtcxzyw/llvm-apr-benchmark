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
import json
import llvm_helper

method_name = os.environ["LAB_METHOD_NAME"]
method_url = os.environ["LAB_METHOD_URL"]
base_model_name = os.environ["LAB_BASE_MODEL_NAME"]
base_model_url = os.environ["LAB_BASE_MODEL_URL"]
fix_dir = sys.argv[1]
output_file = sys.argv[2]

with open(output_file, "w") as f:
    fixes = []
    with_hint = False
    for file in os.listdir(fix_dir):
        if not file.endswith(".json"):
            continue
        with open(os.path.join(llvm_helper.dataset_dir, file)) as info:
            info = json.load(info)
            if not info.get("verified", False):
                continue
            bug_id = info["bug_id"]
            bug_type = info["bug_type"]

        with open(os.path.join(fix_dir, file)) as fix_file:
            cert = json.load(fix_file)
            if "knowledge" in cert:
                for k, v in cert["knowledge"]:
                    if k.startswith("hint"):
                        with_hint = True
                        break
            cert["bug_id"] = bug_id
            cert["bug_type"] = bug_type
            fixes.append(cert)
    json.dump(
        {
            "method_name": method_name,
            "method_url": method_url,
            "base_model_name": base_model_name,
            "base_model_url": base_model_url,
            "with_hint": with_hint,
            "fixes": fixes,
        },
        f,
    )
