import json
from datetime import datetime


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