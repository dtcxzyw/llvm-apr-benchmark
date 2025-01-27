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
import re

sys.path.append(os.path.join(os.path.dirname(os.environ["LAB_DATASET_DIR"]), "scripts"))
import llvm_helper
from lab_env import Environment as Env
from openai import OpenAI

token = os.environ["LAB_LLM_TOKEN"]
url = os.environ.get("LAB_LLM_URL", "https://api.deepseek.com")
model = os.environ.get("LAB_LLM_MODEL", "deepseek-reasoner")
basemodel_cutoff = os.environ.get("LAB_LLM_BASEMODEL_CUTOFF", "2023-12-31Z")
client = OpenAI(api_key=token, base_url=url)
temperature = 0.0
max_input_tokens = 65536
fix_dir = os.environ["LAB_FIX_DIR"]
os.makedirs(fix_dir, exist_ok=True)


def estimate_input_tokens(messages):
    return sum(len(chat["content"]) for chat in messages) * 0.3


def append_message(messages, full_messages, message, dump=True):
    role = message["role"]
    content = message["content"]
    if dump:
        print(f"{role}: {content}")
    messages.append({"role": role, "content": content})
    full_messages.append(message)


def chat(messages, full_messages):
    reasoning_content = ""
    content = ""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            timeout=300,
            temperature=temperature,
        )

        print("assistant:")
        thinking = False
        for chunk in response:
            if (
                hasattr(chunk.choices[0].delta, "reasoning_content")
                and chunk.choices[0].delta.reasoning_content
            ):
                if not thinking:
                    print("Thinking: ", end="")
                    thinking = True
                val = chunk.choices[0].delta.reasoning_content
                print(val, end="")
                reasoning_content += val
            elif chunk.choices[0].delta.content:
                content += chunk.choices[0].delta.content
        print("Answer:")
        print(content)
    except json.JSONDecodeError as e:
        print(e)
        print(e.doc)
        raise e
    answer = {"role": "assistant", "content": content}
    if len(reasoning_content) > 0:
        answer["reasoning_content"] = reasoning_content
    append_message(messages, full_messages, answer, dump=False)
    return content


format_requirement = """
Please answer with the code directly. Do not include any additional information in the output.
Please answer with the complete code snippet (including the unmodified part) that replaces the original code. Do not answer with a diff.
"""


def get_system_prompt() -> str:
    return (
        """You are an LLVM maintainer.
You are fixing a middle-end bug in the LLVM project."""
        + format_requirement
    )


def get_hunk(env: Env) -> str:
    lineno = env.get_hint_line_level_bug_locations()
    bug_file = next(iter(lineno.keys()))
    bug_hunks = next(iter(lineno.values()))
    min_lineno = 1e9
    max_lineno = 0
    for range in bug_hunks:
        min_lineno = min(min_lineno, range[0])
        max_lineno = max(max_lineno, range[1])
    margin = 30
    base_commit = env.get_base_commit()
    source_code = str(
        llvm_helper.git_execute(["show", f"{base_commit}:{bug_file}"])
    ).splitlines()
    min_lineno = max(min_lineno - margin, 1)
    max_lineno = min(max_lineno + margin, len(source_code))
    hunk = "\n".join(source_code[min_lineno - 1 : max_lineno])
    return bug_file, hunk


def extract_code_from_reply(tgt: str):
    if tgt.startswith("```"):
        tgt = tgt.strip().removeprefix("```cpp").removeprefix("```").removesuffix("```")
        return tgt
    # Match the last code block
    re1 = re.compile("```cpp([\s\S]+)```")
    matches = re.findall(re1, tgt)
    if len(matches) > 0:
        return matches[-1]
    re2 = re.compile("```([\s\S]+)```")
    matches = re.findall(re2, tgt)
    if len(matches) > 0:
        return matches[-1]
    return tgt


def modify_inplace(file, src, tgt):
    tgt = extract_code_from_reply(tgt)
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


def issue_fixing_iter(
    env: Env, file, src, messages, full_messages, context_requirement
):
    env.reset()
    tgt = chat(messages, full_messages)
    modify_inplace(file, src, tgt)
    res, log = env.check_full()
    if res:
        return True
    append_message(
        messages,
        full_messages,
        {
            "role": "user",
            "content": "Feedback:\n"
            + normalize_feedback(log)
            + "\nPlease adjust code according to the feedback."
            + format_requirement
            + context_requirement,
        },
    )
    return False


def normalize_messages(messages):
    return {"model": model, "messages": messages}


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
    full_messages = []  # Log with COT tokens
    append_message(
        messages, full_messages, {"role": "system", "content": get_system_prompt()}
    )
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
    desc += f"Please modify the following code in {file}:{bug_func_name} to fix the bug:\n```cpp\n{hunk}\n```\n"
    prefix = "\n".join(hunk.splitlines()[:5])
    suffix = "\n".join(hunk.splitlines()[-5:])
    context_requirement = f"Please make sure the answer includes the prefix:\n```cpp\n{prefix}\n```\nand the suffix:\n```cpp\n{suffix}\n```\n"
    desc += format_requirement + context_requirement
    append_message(messages, full_messages, {"role": "user", "content": desc})
    for idx in range(4):
        print(f"Round {idx + 1}")
        if estimate_input_tokens(messages) > max_input_tokens:
            return
        if issue_fixing_iter(
            env, file, hunk, messages, full_messages, context_requirement
        ):
            cert = env.dump(normalize_messages(full_messages))
            print(cert)
            with open(fix_log_path, "w") as f:
                f.write(json.dumps(cert, indent=2))
            return
    cert = env.dump(normalize_messages(full_messages))
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
