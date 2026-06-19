import re
import subprocess
import os
import glob
import chardet
import json



def extract_errors_from_td(file_path):
    errors = []
    with open(file_path, 'r') as file:
        content = file.read()
        pattern = r'def\s+(\w+)\s*:\s*Error\s*<(.*?)>(,|;)'
        matches = re.finditer(pattern, content, re.DOTALL)
        for match in matches:
            error_name = match.group(1)
            errors.append(error_name)
            error_message = match.group(2)
    # with open(file_path, 'r') as file:
    #     content = file.read()
    #     pattern = r'def\s+(\w+)\s*:\s*ExtWarn\s*<(.*?)>(,|;)'
    #     matches = re.finditer(pattern, content, re.DOTALL)
    #     for match in matches:
    #         error_name = match.group(1)
    #         errors.append(error_name)
    #         error_message = match.group(2)
    return errors



def main():
    all_errors = []
    for td_file in glob.glob('/shared/data1/Users/l1065028/llvm-project/clang/include/clang/Basic/*.td'):
        all_errors.extend(extract_errors_from_td(td_file))
        
    with open('/shared/data1/Users/l1065028/llvm-project/clang/test/output.txt', 'r') as file:
        input_text = file.read()

    pattern = r"Diag ID: (\d+) Located at: (.+):(\d+)"
    matches = re.findall(pattern, input_text)

    unique_diag = {}
    for diag_id, file_name, line_number in matches:
        if diag_id not in unique_diag:
            unique_diag[diag_id] = {"file name": file_name, "line number": int(line_number)}

    result = [{"Diag ID": int(diag_id), **details} for diag_id, details in unique_diag.items()]
    diags = [diag for diag in unique_diag.keys()]

    errs_in_test = []
    with open('diag_results.txt', 'w') as output_file:
        for diag_id in diags:
            try:
                command = ["diagtool", "find-diagnostic-id", diag_id]
                process = subprocess.run(command, capture_output=True, text=True, check=True)
                output_file.write(f"Diag ID: {diag_id}: ")
                errs_in_test.append(process.stdout[:-1])
                output_file.write(process.stdout)
            except subprocess.CalledProcessError as e:
                output_file.write(f"Diag ID: {diag_id} failed with error:\n")
                output_file.write(e.stderr)
    not_included = []
    for i in all_errors:
        if i not in errs_in_test:
            not_included.append(i)
    with open('not_included.txt', 'w') as output_file:
        for i in not_included:
            output_file.write(i)
            output_file.write('\n')
                


if __name__ == "__main__":
    main()
