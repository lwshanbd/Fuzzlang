import json
import re
import subprocess
import os
from datetime import datetime

def get_line_at_offset(content, offset):
    start = content.rfind('\n', 0, offset) + 1
    end = content.find('\n', offset)
    if end == -1:
        end = len(content)
    
    # Check for line continuation
    while content[end-1] == '\\':
        next_end = content.find('\n', end + 1)
        if next_end == -1:
            end = len(content)
            break
        end = next_end
    
    return content[start:end]

def get_ast_string(node, depth=0):
    result = '  ' * depth + f"{node.kind}: {node.spelling}\n"
    for child in node.get_children():
        result += get_ast_string(child, depth + 1)
    return result


def find_node_at_offset(node, target_offset):
    if node.extent.start.offset <= target_offset < node.extent.end.offset:
        for child in node.get_children():
            result = find_node_at_offset(child, target_offset)
            if result:
                return result
        return node
    return None

def log_to_json(fuzz_mode, fuzzed_args, original_command, new_command_line, status, message, log_file_path):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "fuzz_mode": fuzz_mode,
        "fuzzed_args": fuzzed_args,
        "original_command": original_command,  # Convert list to string for logging
        "fuzzed_command": new_command_line,
        "status": status,
        "message": message
    }

    with open(log_file_path, 'a') as log_file:
        json.dump(log_entry, log_file)
        log_file.write('\n')  # Add newline for readability


def log_to_json(fuzz_mode, original_line, modified_line, node_kind, status, message, log_file_path):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "fuzz_mode": fuzz_mode,
        "original_line": original_line,
        "modified_line": modified_line,
        "node_kind": str(node_kind),
        "status": status,
        "message": message
    }
    with open(log_file_path, 'a') as log_file:
        json.dump(log_entry, log_file)
        log_file.write('\n')  # Add newline for readability
        
def log_to_json_1(file_name, fuzz_mode, status, message, log_file_path):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "file": file_name,
        "fuzz_mode": fuzz_mode,
        "status": status,
        "message": message
    }
    with open(log_file_path, 'a') as log_file:
        json.dump(log_entry, log_file)
        log_file.write('\n')  # Add newline for readability
        
# def log_to_json(file_name, fuzz_mode, status, message, log_file_path, diff):
#     log_entry = {
#         "timestamp": datetime.now().isoformat(),
#         "file": file_name,
#         "fuzz_mode": fuzz_mode,
#         "status": status,
#         "message": message,
#         "diff": diff
#     }
#     with open(log_file_path, 'a') as log_file:
#         json.dump(log_entry, log_file)
#         log_file.write('\n')  # Add newline for readability
        
def get_error_name(diagID):
    try:
        diag_command = ["diagtool", "find-diagnostic-id", diagID]
        process = subprocess.run(
            diag_command, capture_output=True, text=True, check=True)
        error_name = process.stdout.split('\n')[0]
        return error_name
    except:
        print("Failed to run diagtool")
        return False

def code_deformat(code):
    return code.replace("```python", "").replace("```cpp", "")\
        .replace("```c++", "").replace("```c", "").replace("```", "")


def extract_error_names(error_message):
    diag_ids = re.findall(r"DiagID:\s*(\d+)", error_message)
    return [get_error_name(diag_id) for diag_id in diag_ids]


def get_all_files(directory):
    file_paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_paths.append(os.path.join(root, file))
    return file_paths