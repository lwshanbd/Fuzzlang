#!/usr/tce/packages/python/python-3.9.12/bin/python

"""This script wraps the compiler, fuzzes the command line arguments, and executes the compiler with the fuzzed arguments."""

import subprocess
import sys
import random
import json
import os
from datetime import datetime

RECOGNIZED_SOURCE_FILE_EXTENSIONS = ['.c', '.cpp', '.cxx', '.cc', '.c++']
log_file_path = '/p/lustre3/shan4/Fuzzlang/error_log1.json'
fuzz_modes = []
remove_level = 0

# Fuzz the command line arguments based on the FUZZ_MODE environment
# Fuzz mode:
#  1 - reorder: Randomly reorder the arguments
#  2 - remove: Randomly remove a subset of the arguments
#  3 - replace: Randomly replace a subset of the arguments
#  4 - insert: Randomly insert a subset of the arguments
# Remove level:
#  1 - low: Remove 1 of the arguments
#  2 - medium: Remove 1 to 1/2 of the arguments
#  3 - high: Remove 1/2 to all of the arguments
def parse_fuzz_mode():
    # Get the FUZZ_MODE environment variable
    fuzz_mode = os.getenv('FUZZ_MODE', '')
    remove_level = os.getenv('REMOVE_LEVEL', '')
    
    # Print the original FUZZ_MODE value
    print(f"Original FUZZ_MODE: {fuzz_mode}")
    
    # Handle different separators & and ,
    separators = [',', '&']
    for sep in separators:
        if sep in fuzz_mode:
            fuzz_mode = fuzz_mode.replace(sep, ' ')
    
    # Split the string into individual modes
    modes = fuzz_mode.split()
    
    # Remove any potential empty strings and duplicates
    modes = list(set([mode.strip() for mode in modes if mode.strip()]))
    for mode in modes:
        if mode == 'reorder':
            fuzz_modes.append('reorder')
        elif mode == 'remove':
            fuzz_modes.append('remove')
        elif mode == 'replace':
            fuzz_modes.append('replace')
        elif mode == 'insert':
            fuzz_modes.append('insert')
        else:
            print(f"Invalid fuzz mode: {mode}")
    if remove_level:
        try:
            remove_level = int(remove_level)
        except ValueError:
            print(f"Invalid remove level: {remove_level}")
            print("Remove level must be an integer value between 1 and 3")


def log_to_json(fuzzed_args, original_command, new_command_line, status, message):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "fuzzed_args": fuzzed_args,
        "original_command": original_command,  # Convert list to string for logging
        "fuzzed_command": new_command_line,
        "status": status,
        "message": message
    }
    
    with open(log_file_path, 'a') as log_file:
        json.dump(log_entry, log_file)
        log_file.write('\n')  # Add newline for readability


def recognize_source_file_extension(file_path):
    for recognized_extension in RECOGNIZED_SOURCE_FILE_EXTENSIONS:
        if file_path.endswith(recognized_extension):
            return True

    return False

def fuzz_remove(command_line):
    args_to_fuzz = command_line['other_params']

    # Randomly determine the number of arguments to remove
    if remove_level == 1:
        num_to_remove = 1
    elif remove_level == 2:
        num_to_remove = random.randint(1, int(len(args_to_fuzz)/2))
    elif remove_level == 3:
        num_to_remove = random.randint(int(len(args_to_fuzz)/2), len(args_to_fuzz))
    else:
        num_to_remove = random.randint(1, len(args_to_fuzz))    
    fuzzed_args = random.sample(args_to_fuzz, num_to_remove)

    # Create a new list of arguments excluding the randomly selected ones
    fuzzed_args = [arg for arg in args_to_fuzz if arg not in fuzzed_args]

    # Build the new command line
    new_command_line = []
    new_command_line.append(command_line['compiler'])
    if command_line['source_file']:
        new_command_line.extend(command_line['source_file'])
    if command_line['output_flag']:
        new_command_line.append(command_line['output_flag'])
        new_command_line.append(command_line['output_file'])
    backup_command_line = new_command_line.copy()
    backup_command_line.extend(args_to_fuzz)
    new_command_line.extend(fuzzed_args)
    
    # Execute the new command line
    try:
        result = subprocess.run(
            new_command_line, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_to_json(fuzzed_args, backup_command_line, new_command_line, "SUCCESS", result.stdout.decode().strip())
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        log_to_json(fuzzed_args, backup_command_line, new_command_line, "ERROR", error_message)
        subprocess.run(backup_command_line, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def fuzz_reordering(command_line):
    args_to_fuzz = command_line['other_params']

    # Randomly shuffle the arguments
    random.shuffle(args_to_fuzz)

    # Build the new command line
    new_command_line = []
    new_command_line.append(command_line['compiler'])
    if command_line['source_file']:
        new_command_line.extend(command_line['source_file'])
    if command_line['output_flag']:
        new_command_line.append(command_line['output_flag'])
        new_command_line.append(command_line['output_file'])
    backup_command_line = new_command_line.copy()
    backup_command_line.extend(args_to_fuzz)
    new_command_line.extend(args_to_fuzz)
    
    # Execute the new command line
    try:
        result = subprocess.run(
            new_command_line, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_to_json(None, backup_command_line, new_command_line, "SUCCESS", result.stdout.decode().strip())
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        log_to_json(None, backup_command_line, new_command_line, "ERROR", error_message)
        subprocess.run(backup_command_line, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def parse_clang_command(command_line):
    args = command_line
    # Initialize components
    if "++" in args[0]:
        compiler = 'clang++'
    else:
        compiler = 'clang'
    source_file = []
    output_flag = None
    output_file = None
    other_params = []

    # Identify components
    i = 1  # Skip the compiler
    while i < len(args):
        arg = args[i]
        if recognize_source_file_extension(arg):
            source_file.append(arg)
        elif arg == '-o' and i + 1 < len(args):
            output_flag = arg
            output_file = args[i + 1]
            i += 1  # Increment to move to the next argument
        else:
            other_params.append(arg)
        i += 1  # Increment to move to the next argument

    return {
        'compiler': compiler,
        'source_file': source_file,
        'output_flag': output_flag,
        'output_file': output_file,
        'other_params': other_params
    }


# Example usage
if __name__ == "__main__":
    command = sys.argv
    parse_fuzz_mode()
    parsed_command = parse_clang_command(command)
    fuzz_mode = random.choice(fuzz_modes)
    if fuzz_mode == 'reorder':
        fuzz_reordering(parsed_command)
    elif fuzz_mode == 'remove':
        fuzz_remove(parsed_command)
    
