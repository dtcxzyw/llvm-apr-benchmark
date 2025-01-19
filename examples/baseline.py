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
import os
import json

sys.path.append(os.path.join(os.path.dirname(os.environ["LAB_DATASET_DIR"]), "scripts"))
import llvm_helper
from lab_env import Environment as Env
from openai import OpenAI

token = os.environ["LAB_LLM_TOKEN"]
url = os.environ.get("LAB_LLM_URL", "https://api.deepseek.com")
model = os.environ.get("LAB_LLM_MODEL", "deepseek-chat")
basemodel_cutoff = os.environ.get("LAB_LLM_BASEMODEL_CUTOFF", "2023-12-31Z")
client = OpenAI(api_key=token, base_url=url)
temperature = 0.0
max_input_tokens = 65536
fix_dir = os.environ["LAB_FIX_DIR"]
os.makedirs(fix_dir, exist_ok=True)


def estimate_input_tokens(messages):
    characters = 0
    for chat in messages:
        if isinstance(chat, dict):
            characters += len(chat["content"])
        else:
            characters += len(chat.content)
    return characters * 0.3


def append_message(messages, message):
    if isinstance(message, dict):
        role = message["role"]
        content = message["content"]
    else:
        role = message.role
        content = message.content
    print(f"{role}: {content}")
    messages.append(message)


def chat(messages):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False,
        timeout=300,
        temperature=temperature,
    )
    answer = response.choices[0].message
    append_message(messages, answer)
    return answer.content


def get_system_prompt() -> str:
    return """You are an LLVM maintainer.
You are fixing a middle-end bug in the LLVM project.
Please answer with the code directly. Do not include any additional information.
"""


def get_hunk(env: Env) -> str:
    lineno = env.get_hint_line_level_bug_locations()
    bug_file = next(iter(lineno.keys()))
    bug_hunks = next(iter(lineno.values()))
    min_lineno = 1e9
    max_lineno = 0
    for range in bug_hunks:
        min_lineno = min(min_lineno, range[0])
        max_lineno = max(max_lineno, range[1])
    margin = 15
    base_commit = env.get_base_commit()
    source_code = str(
        llvm_helper.git_execute(["show", f"{base_commit}:{bug_file}"])
    ).splitlines()
    min_lineno = max(min_lineno - margin, 1)
    max_lineno = min(max_lineno + margin, len(source_code))
    hunk = "\n".join(source_code[min_lineno - 1 : max_lineno])
    return bug_file, hunk


def modify_inplace(file, src, tgt):
    tgt = tgt.removeprefix("```cpp").removeprefix("```").removesuffix("```").strip()
    path = os.path.join(llvm_helper.llvm_dir, file)
    with open(path) as f:
        code = f.read()
    code = code.replace(src, tgt)
    with open(path, "w") as f:
        f.write(code)


def get_issue_desc(env: Env) -> str:
    issue = env.get_hint_issue()
    if issue is None:
        return ""
    title = issue["title"]
    body = issue["body"]
    return f"Issue title: {title}\nIssue body: {body}\n"


def normalize_feedback(log) -> str:
    if not isinstance(log, list):
        return str(log)
    return json.dumps(llvm_helper.get_first_failed_test(log), indent=2)


def issue_fixing_iter(env: Env, file, src, messages):
    env.reset()
    tgt = chat(messages)
    modify_inplace(file, src, tgt)
    res, log = env.check_full()
    if res:
        return True
    append_message(
        messages,
        {
            "role": "user",
            "content": "Feedback:\n"
            + normalize_feedback(log)
            + "\nPlease adjust code according to the feedback. Do not include any additional information.\n",
        },
    )
    return False


def normalize_messages(messages):
    normalized = []
    for message in messages:
        if isinstance(message, dict):
            normalized.append(message)
        else:
            normalized.append({"role": message.role, "content": message.content})
    return normalized


override = False


def fix_issue(issue_id):
    fix_log_path = os.path.join(fix_dir, f"{issue_id}.json")
    if not override and os.path.exists(fix_log_path):
        print(f"Skip {issue_id}")
        return
    print(f"Fixing {issue_id}")
    env = Env(issue_id, basemodel_cutoff)
    bug_funcs = env.get_hint_bug_functions()
    if len(bug_funcs) != 1 or len(next(iter(bug_funcs.values()))) != 1:
        raise RuntimeError("Multi-func bug is not supported")
    messages = []
    append_message(messages, {"role": "system", "content": get_system_prompt()})
    bug_type = env.get_bug_type()
    bug_func_name = next(iter(bug_funcs.values()))[0]
    component = next(iter(env.get_hint_components()))
    desc = f"This is a {bug_type} bug in {component}.\n"
    desc += get_issue_desc(env)
    env.reset()
    res, log = env.check_fast()
    assert not res
    desc += "Detailed information:\n"
    desc += normalize_feedback(log) + "\n"
    file, hunk = get_hunk(env)
    desc += f"Please modify the following code in {file}:{bug_func_name} to fix the bug:\n```\n{hunk}\n```\n"
    append_message(messages, {"role": "user", "content": desc})
    for idx in range(4):
        print(f"Round {idx + 1}")
        if estimate_input_tokens(messages) > max_input_tokens:
            return
        if issue_fixing_iter(env, file, hunk, messages):
            cert = env.dump(normalize_messages(messages))
            print(cert)
            with open(fix_log_path, "w") as f:
                f.write(json.dumps(cert, indent=2))
            return
    cert = env.dump(normalize_messages(messages))
    with open(fix_log_path, "w") as f:
        f.write(json.dumps(cert, indent=2))


if len(sys.argv) == 1:
    task_list = sorted(
        map(lambda x: x.removesuffix(".json"), os.listdir(llvm_helper.dataset_dir))
    )
else:
    task_list = [sys.argv[1]]
    if len(sys.argv) == 3 and sys.argv[2] == "-f":
        override = True

for task in task_list:
    fix_issue(task)
    # try:
    #     fix_issue(task)
    # except Exception as e:
    #     print(e)
    #     pass
