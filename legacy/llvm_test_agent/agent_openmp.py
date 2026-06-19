import json
import re
import logging
import subprocess
import shutil
import traceback
import random
from openai import OpenAI

command_message = "You are an expert in high-performance computing, specializing in OpenCL code development. I will provide a Clang test related to OpenCL, potentially containing compilation commands. Your task is to extract or construct a valid compilation command for the test and return it as a Python list in comma-separated format. Every item must be string. Key requirements: The source file should be tmp.cpp or tmp.c. Use the newest C++ standard if multiple are available. Exclude arguments containing -verify or -code-completion-at. Do not include any header files in the command. Replace %s with tmp.c or tmp.cpp. If no compilation command is provided, generate one yourself that adheres to the above constraints. Do not include any explanations or additional details"

def process_command(command):
    i = 0
    while i < len(command):
        if "clang_cc1" in command[i]:
            command[i] = 'clang'
            command.insert(i + 1, '-cc1')
            i += 1
        if "%itanium_abi_triple" in command[i]:
            command[i] = 'x86_64-unknown-linux-gnu'
        i += 1
    return command

def code_deformat(code):
    if code[0] == '`' and code[1] != '`':
        return code[1:-1]
    return code.replace("```python", "").replace("```cpp", "")\
        .replace("```c++", "").replace("```c", "").replace("```", "")

def run_command_w_code_omp(command, code, code_type):
    if code_type == 'c':
        with open('tmp.c', 'w') as file:
            file.write(code)
        if "tmp.cpp" in command:
            command[command.index("tmp.cpp")] = "tmp.c"
    else:
        with open('tmp.cpp', 'w') as file:
            file.write(code)
        if "tmp.c" in command:
            command[command.index("tmp.c")] = "tmp.cpp"
    # Run with multiple C++ Standards
    if "," not in str(command):
        return [], False
    omp_standards = ["-fopenmp-version=45", "-fopenmp-version=50", "-fopenmp-version=51", "-fopenmp-version=52", "-fopenmp-version=60"]
    ocl_standards = ["-cl-std=clc++1.0", "-cl-std=clc++1.1", "-cl-std=clc++1.2", "-cl-std=clc++2.0", "-cl-std=clc++2.1", "-cl-std=clc++3.0"]
    cpp_standards= ["-std=c++98", "-std=c++03", "-std=c++11", "-std=c++14", "-std=c++17", "-std=c++20"]
    
    all_diagids = []
    err_msg = ""
    command = [arg for arg in command if not arg.startswith("-fopenmp-version")]
    for omp_std in ocl_standards:
        command.append(omp_std)
        try:
            process = subprocess.run(
                command, capture_output=True, text=True, check=True, timeout=10)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr
            matches = re.findall(r"DiagID:\s*(\d+)\n", err_msg)
            diagids = [int(match) for match in matches]
            all_diagids.extend(diagids)
        except subprocess.TimeoutExpired:
            return [], False
        finally:
            command = command[:-1]
    return all_diagids, err_msg



def generate_code_omp(diagID, lines, code_type, line_number, llm_model):
    client = OpenAI()
    err_line_number = line_number
    error_lines = lines[line_number-1]
    while "expected-error" not in error_lines and line_number > 1:
        line_number -= 1
        error_lines = lines[line_number-1] + '\n' + error_lines

    # Part 0 Extract Compile Command
    compile_message = [{"role": "system", "content": command_message}]
    run_lines = [line for line in lines if line.startswith("// RUN:")][:5]
    if (len(run_lines) == 0):
        compile_message.append(
            {"role": "user", "content": "The code is" + str(lines)})
    else:
        compile_message.append(
            {"role": "user", "content": "The code is" + str(run_lines)})
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=compile_message
    )
    reply = completion.choices[0].message.content
    command = eval(code_deformat(reply))
    command = process_command(command)
    # Part 1 Generate Reproduced Code from Clang Test
    messages = [{"role": "system", "content": f"Suppose you are an expert in the field of computer science, proficient in C++ and LLVM development. You are required to reproduce {code_type} code based on the provided code. The code is from Clang tests and includes expected-error annotations. Please provide a new piece of code that reproduces the error I have given you. If you are reproducing OpenCL-related errors, please note that some directives require a code block enclosed in braces immediately following them. Add them as needed. Note that some variables need necessary initialization, and some functions require necessary declarations. Please ensure that the declared variables follow the declaration style provided in the code I gave you, paying special attention to whether they are single variables or pointer variables. Please don't include 'omp.h' and other header file. OpenCL blocks cannot be placed outside of functions. I only need the code, no additional explanations."}]
    # 
    try:
        diag_command = ["diagtool", "find-diagnostic-id", diagID]
        process = subprocess.run(
            diag_command, capture_output=True, text=True, check=True)
        error_name = process.stdout.split('\n')[0]
    except:
        print("Failed to run diagtool")
        return False
    if llm_model == "gpt-4o-mini":
        print(error_name)

    messages.append(
        {"role": "user", "content": "Expected error name is" + str(error_name) + ". The code is" + str(error_lines)})
    completion = client.chat.completions.create(
        model=llm_model,
        messages=messages
    )
    reply = completion.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    repro_code = code_deformat(reply)
    IDs, err_msg = run_command_w_code_omp(command, repro_code, code_type)
    # LLM understood the error and reproduce it
    if int(diagID) in IDs:
        return True
    # Part 2 LLM failed to reproduce the error. regenerate with more test code
    messages.append(
        {"role": "user", "content": "The code you just tried to reproduce did not reproduce the error I gave you, I will now give you a more complete piece of test code, please reproduce it again. Please note that the code you reproduce for me should be as concise as possible, preferably containing only the error in " + str(lines[err_line_number-1]) + " and no other errors. If you are reproducing OpenCL-related errors, please note that some directives require a code block enclosed in braces immediately following them. Add them as needed. Please don't include 'omp.h' and other header file. Note that some variables need necessary initialization, and some functions require necessary declarations. Please ensure that the declared variables follow the declaration style provided in the code I gave you, paying special attention to whether they are single variables or pointer variables. OpenCL blocks cannot be placed outside of functions. Expected error name is" + str(error_name) + " The code is" + str(lines)})
    completion = client.chat.completions.create(
        model=llm_model,
        messages=messages
    )
    reply = completion.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    repro_code = code_deformat(reply)
    IDs, err_msg = run_command_w_code_omp(command, repro_code, code_type)

    if int(diagID) in IDs:
        return True
    if llm_model == "gpt-4o":
        logging.info(f"Compile Command: {command}")
        logging.info(f"Error Message: {err_msg}")
        logging.info(f"IDs: {IDs}")
    return False

