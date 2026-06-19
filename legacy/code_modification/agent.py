
import json
import re
import logging
import subprocess
import os
import tempfile
import difflib
import utils

from utils import log_to_json, get_line_at_offset, get_ast_string, find_node_at_offset


from openai import OpenAI




def run(file_name, original_command, log_file_path):
    error_file_path = "/shared/data1/Users/l1065028/Fuzzlang/src/llvm_test_agent/success_files/"
    error_files = utils.get_all_files(error_file_path)
    for error_file in error_files[0:1]:
        run_with_error(file_name, original_command, log_file_path, error_file)
        

def run_with_error(file_name, original_command, log_file_path, error_file):
    client = OpenAI()
    error_name = error_file.split('/')[-1].replace('.cpp','').replace('.c','')
    with open(error_file, 'r') as error_f:
        errors = error_f.read()

    with open(file_name, 'r') as file:
        content = file.read()

    messages = [{"role": "system", "content": f"Suppose you are an expert in the field of computer science, proficient in C++ and LLVM development. I now have a copy of the code, and a sample error code, please model the sample error code after the sample error code and inject the same error into the correct code so that the correct code produces the same error. Please note that you don't have to give me any explanation, just the code. If you don't think there is a way to inject, please output “N”."}]

    messages.append(
        {"role": "user", "content": f"The error code is {errors}, the correct code is {content}"})

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )

    reply = completion.choices[0].message.content
    if reply == "N":
        print("NO!")
        return False
    repro_code = utils.code_deformat(reply)

    with tempfile.NamedTemporaryFile(mode='w+', suffix='.cpp') as temp_file:
            # Write the modified content to the temporary file
            temp_file.write(repro_code)
            temp_file.flush()

            command_to_run = original_command.copy()
            for idx, element in enumerate(command_to_run):
                if element == file_name:
                    command_to_run[idx] = temp_file.name
                    break

            try:
                result = subprocess.run(
                    command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                utils.log_to_json_1(file_name, "Agent", "SUCCESS", result.stdout.decode().strip(), log_file_path)
                print("NO!")
                return False
            except subprocess.CalledProcessError as e:
                error_message = e.stderr.decode()
                result = subprocess.run(['diff', file_name, temp_file.name], 
                              capture_output=True, 
                              text=True)
                error_diff = result.stdout

                log_to_json(file_name, "Agent", "ERROR", error_message, log_file_path, error_diff)
                error_names = utils.extract_error_names(error_message)

                if error_name in error_names:
                    print("Error injected successfully")
                    return True
                else:
                    print("NO!")

                return False
                
