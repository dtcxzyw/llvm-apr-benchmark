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
import requests
import json

github_token = os.environ["LAB_GITHUB_TOKEN"]
postfix_extract = os.path.join(os.path.dirname(__file__), "postfix_extract.py")
session = requests.Session()
session.headers.update(
    {
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
    }
)
print(json.dumps(session.get("https://api.github.com/rate_limit").json(), indent=2))
