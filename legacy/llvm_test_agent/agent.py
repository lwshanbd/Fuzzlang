import json
import re
import logging
import subprocess
import shutil
import traceback
import random

from openai import OpenAI
import agent_openmp
command_message = "Suppose you are an expert in the field of computer science and proficient in C/C++ and LLVM development. I’ll provide you with the lines of a Clang test, which may contain some compilation commands. I have some refactored code and want to reproduce this test. Please select exactly one complete compilation command and return it to me in Python list format, **separated by commas**. Note that the source code file is either tmp.cpp or tmp.c. If multiple C++ standards are available, please use the newer C++ standard. Do not use any argument with `-verify` or `-code-completion-at`. Please don't include any header file. Please replace '%s' with tmp.c/tmp.cpp. If the code given to you does not contain a compile command, please generate one for me yourself. Please remember to add the source files tmp.c/tmp.cpp. No further explanations, please."


logging.basicConfig(
    filename='opencl.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
error_name = ''


def get_error_name(diagID):
    try:
        diag_command = ["diagtool", "find-diagnostic-id", diagID]
        process = subprocess.run(
            diag_command, capture_output=True, text=True, check=True)
        error_name = process.stdout.split('\n')[0]
        return error_name
    except:
        print("Failed to run diagtool")
        print(diagID)
        return ""


def code_deformat(code):
    if code[0] == '`' and code[1] != '`':
        return code[1:-1]
    return code.replace("```python", "").replace("```cpp", "")\
        .replace("```c++", "").replace("```c", "").replace("```", "")


def extract_errors():
    with open('output.txt', 'r') as file:
        input_text = file.read()
    pattern = r"Diag ID: (\d+) Located at: (.+):(\d+)"
    matches = re.findall(pattern, input_text)

    unique_diag = {}
    for diag_id, file_name, line_number in matches:
        # if "OpenMP" not in file_name:
        #     continue
        # if "OpenCL" in file_name:
        #     continue
        if diag_id not in unique_diag:
            unique_diag[diag_id] = [{
                "file_name": file_name, "line_number": int(line_number)}]
        elif diag_id in unique_diag:
            unique_diag[diag_id].append(
                {"file_name": file_name, "line_number": int(line_number)})
    return unique_diag


def extract_finished_errors():
    input_text = ""
    for file_name in ['4o-mini-success.txt']: # '4o-mini-success.txt', 
        with open(file_name, 'r') as file:
            input_text += file.read()
    pattern = r"Diag ID: (\d+), file_name: (.+?), line number: (.+?)"
    matches = re.findall(pattern, input_text)
    diags = []
    for match in matches:
        diag_id = match[0]
        diags.append(diag_id)
    return diags


def extract_lines(diag):
    file_name = diag['file_name']
    with open(file_name, 'r') as file:
        content = file.read()
        content_lines = content.split('\n')
    return content_lines

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


def run_command_w_code(command, code, code_type):
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
    cpp_standards= ["-std=c++98", "-std=c++03", "-std=c++11", "-std=c++14", "-std=c++17", "-std=c++20"]
    if code_type == 'cpp':
        all_diagids = []
        err_msg = ""
        command = [arg for arg in command if not arg.startswith("-std=c++")]
        for std in cpp_standards:
            command.append(std)
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
    # print(command)
    try:
        process = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=10)
        return [], False
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr
        matches = re.findall(r"DiagID:\s*(\d+)\n", err_msg)
        diagids = [int(match) for match in matches]
        return diagids, err_msg
    except subprocess.TimeoutExpired:
        return [], False


def generate_code(diagID, lines, code_type, line_number, llm_model):
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
    messages = [{"role": "system", "content": f"Suppose you are an expert in the field of computer science, proficient in C++ and LLVM development. You are required to reproduce {code_type} code based on the provided code. The code is from Clang tests and includes expected-error annotations. Please provide a new piece of code that reproduces the error I have given you. If you are reproducing OpenMP-related errors, please note that some directives require a code block enclosed in braces immediately following them. Add them as needed. Note that some variables need necessary initialization, and some functions require necessary declarations. Please ensure that the declared variables follow the declaration style provided in the code I gave you, paying special attention to whether they are single variables or pointer variables. Please don't include 'omp.h' and other header file. OpenMP blocks cannot be placed outside of functions. I only need the code, no additional explanations."}]
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
    IDs, err_msg = run_command_w_code(command, repro_code, code_type)
    # LLM understood the error and reproduce it
    if int(diagID) in IDs:
        return True
    # Part 2 LLM failed to reproduce the error. regenerate with more test code
    messages.append(
        {"role": "user", "content": "The code you just tried to reproduce did not reproduce the error I gave you, I will now give you a more complete piece of test code, please reproduce it again. Please note that the code you reproduce for me should be as concise as possible, preferably containing only the error in " + str(lines[err_line_number-1]) + " and no other errors. If you are reproducing OpenMP-related errors, please note that some directives require a code block enclosed in braces immediately following them. Add them as needed. Please don't include 'omp.h' and other header file. Note that some variables need necessary initialization, and some functions require necessary declarations. Please ensure that the declared variables follow the declaration style provided in the code I gave you, paying special attention to whether they are single variables or pointer variables. OpenMP blocks cannot be placed outside of functions. Expected error name is" + str(error_name) + " The code is" + str(lines)})
    completion = client.chat.completions.create(
        model=llm_model,
        messages=messages
    )
    reply = completion.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    repro_code = code_deformat(reply)
    IDs, err_msg = run_command_w_code(command, repro_code, code_type)

    if int(diagID) in IDs:
        return True
    if llm_model == "gpt-4o":
        logging.info(f"Compile Command: {command}")
        logging.info(f"Error Message: {err_msg}")
        logging.info(f"IDs: {IDs}")
    return False



def main():
    diags = extract_errors()
    finished_error = extract_finished_errors()
    print(len(set(finished_error)))
    kkk = 0
    for i in set(finished_error):
        error_name = get_error_name(i)
        if "err_" in error_name:
            kkk += 1
    print(f"number of error in 4o:{kkk}")
    keys = list(diags.keys())
    print(len(keys))
    cnt = 0
    random.shuffle(keys)
    omp_errors = []
    for diag in keys:
        continue
        error_name = get_error_name(diag)
        # if "cuda" in error_name:
        #     cnt += 1
        # if "_objc_" in error_name:
        #     cnt += 1
        
        if diag in finished_error:
            omp_errors.append(error_name)
            continue
        
        # if "_omp_" in error_name:
        #     cnt += 1
        continue
        # else:
        #     # error_name = get_error_name(diag)
        #     # if "_objc_" in error_name:
        #     # cnt += 1
        #     continue
        #     file_name = diags[diag]['file_name']
        #     # error_name = get_error_name(diag)
        #     # if error_name.startswith("ext"):
        #     #     cnt -= 1
        #     # if "line-directive" in file_name:
        #     #     cnt -= 1
        #     # if error_name.startswith("err_omp"):
        #     #     cnt -= 1
        #     # continue
        try:
            for i in range(min(3, len(diags[diag]))):
                file_name = diags[diag][i]['file_name']
                error_name = get_error_name(diag)
                # if error_name.startswith("ext"):
                #     continue
                # if "line-directive" in file_name:
                #     continue
                # if "_objc_" in error_name:
                #     continue
                line_number = diags[diag][i]['line_number']

                # print(f"Diag ID: {diag}, file_name: {file_name}, line number: {line_number}")
                lines = extract_lines(diags[diag][i])
                res = False
                code_type = 'c'
                if file_name.endswith('.cpp'):
                    code_type = 'cpp'
                res = agent_openmp.generate_code_omp(diag, lines, code_type,
                                    line_number, 'gpt-4o-mini')

                if res == True:
                    print("OK")
                    success_file = error_name + ".cpp"
                    if code_type == 'c':
                        success_file = error_name + ".c"
                        shutil.copy('tmp.c', "success_files/" + success_file)
                    else:
                        shutil.copy('tmp.cpp', "success_files/" + success_file)
                    with open("4o-mini-success.txt", "a") as file:
                        file.write(
                            f"Diag ID: {diag}, file_name: {file_name}, line number: {line_number}, error_name: {error_name}\n")
                    break
                    continue
                else:
                    print("try 4o...")
                    res = agent_openmp.generate_code_omp(diag, lines, code_type,
                                        line_number, 'gpt-4o')


                if res == True:
                    success_file = error_name + ".cpp"
                    if code_type == 'c':
                        success_file = error_name + ".c"
                        shutil.copy('tmp.c', "success_files/" + success_file)
                    else:
                        shutil.copy('tmp.cpp', "success_files/" + success_file)
                    with open("4o-success.txt", "a") as file:
                        file.write(
                            f"Diag ID: {diag}, file_name: {file_name}, line number: {line_number}, error_name: {error_name}\n")
                    print("OK")
                    break
                else:
                    logging.info(f"Extract Diag Info:")
                    logging.info(
                        f"Diag ID: {diag}, file_name: {file_name}, line number: {line_number}, error_name: {error_name}")
                    failed_file = error_name + ".cpp"
                    if code_type == 'c':
                        failed_file = error_name + ".c"
                        shutil.copy('tmp.c', "failed_files/" + failed_file)
                    else:
                        shutil.copy('tmp.cpp', "failed_files/" + failed_file)
                    print("Failed")
        except Exception as e:
            logging.info("failed running")
            logging.info(e)
            logging.info(traceback.format_exc())
            print("Failed Running")
    print(cnt)
    with open("omp_errors.txt", "w") as file:
        for diag in omp_errors:
            file.write(f"{diag}\n")
    print(len(omp_errors))
    return


if __name__ == "__main__":
    main()
