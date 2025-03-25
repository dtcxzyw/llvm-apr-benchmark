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

import sys
import json
import os

dataset_dir = sys.argv[1]
input_file = sys.argv[2]

os.makedirs(dataset_dir, exist_ok=True)

with open(input_file) as f:
    data = json.load(f)
    for item in data["fixes"]:
        issue_id = item['bug_id']
        with open(os.path.join(dataset_dir, f"{issue_id}.json"), "w") as out:
            json.dump(item, out, indent=2)
