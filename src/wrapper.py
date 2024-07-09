#!/p/lustre2/shan4/anaconda3/bin/python

"""This script wraps the compiler, fuzzes the command line arguments, and executes the compiler with the fuzzed arguments."""

import subprocess
import sys
import random
import json
import os
from datetime import datetime
import clang.cindex
import parentheses
from collections import defaultdict


RECOGNIZED_SOURCE_FILE_EXTENSIONS = ['.c', '.cpp', '.cxx', '.cc', '.c++']
Arg_With_Attached = ['-Xlinker', '-MF', '-MT', '-isystem', '-o', '-D']
Arg_Not_Removed = ['-o', '-I']
log_file_path = '/p/lustre2/shan4/Fuzzlang/log_llvm_removept.json'
fuzz_modes = ['none']
remove_level = 1
command = []
original_command = []
if not clang.cindex.Config.library_file:
    clang.cindex.Config.set_library_file(
        '/p/lustre2/shan4/llvm-trunk/lib/libclang.so')
index = clang.cindex.Index.create()

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
    global remove_level, fuzz_modes
    # Get the FUZZ_MODE environment variable
    fuzz_mode = os.getenv('FUZZ_MODE', '')
    remove_level = os.getenv('REMOVE_LEVEL', '')
    # Print the original FUZZ_MODE value
    # print(f"Original FUZZ_MODE: {fuzz_mode}")

    # Handle different separators & and ,
    separators = [',', '&']
    for sep in separators:
        if sep in fuzz_mode:
            fuzz_mode = fuzz_mode.replace(sep, ' ')
    # Split the string into individual modes
    modes = fuzz_mode.split()
    # Remove any potential empty strings and duplicates
    modes = list(set([mode.strip() for mode in modes if mode.strip()]))
    if modes:
        fuzz_modes.clear()
    for mode in modes:
        if mode == 'reorder':
            fuzz_modes.append('reorder')
        elif mode == 'remove':
            fuzz_modes.append('remove')
        elif mode == 'replace':
            fuzz_modes.append('replace')
        elif mode == 'insert':
            fuzz_modes.append('insert')
        elif mode == 'remove_parentheses':
            fuzz_modes.append('remove_parentheses')
        elif mode == 'none':
            fuzz_modes.append('none')
        else:
            print(f"Invalid fuzz mode: {mode}")
    if remove_level:
        try:
            remove_level = int(remove_level)
        except ValueError:
            print(f"Invalid remove level: {remove_level}")
            print("Remove level must be an integer value between 1 and 3")


def log_to_json(fuzz_mode, fuzzed_args, original_command, new_command_line, status, message):
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


def log_to_json(fuzz_mode, original_line, modified_line, node_kind, status, message):
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


def recognize_source_file_extension(file_path):
    for recognized_extension in RECOGNIZED_SOURCE_FILE_EXTENSIONS:
        if file_path.endswith(recognized_extension):
            return True

    return False


def fuzz_remove(command_line):

    # print(remove_level)
    # print("Removing")
    global command
    args_to_fuzz = command_line['other_params']
    if not args_to_fuzz:
        return
    # Randomly determine the number of arguments to remove
    if remove_level == 1:
        num_to_remove = 1
    elif remove_level == 2:
        num_to_remove = random.randint(1, int(len(args_to_fuzz)/2+1))
    elif remove_level == 3:
        num_to_remove = random.randint(
            int(len(args_to_fuzz)/2), len(args_to_fuzz)-1)
    else:
        num_to_remove = random.randint(1, len(args_to_fuzz)-1)
    fuzzed_args = random.sample(args_to_fuzz, num_to_remove)
    fuzzed_args = [arg for arg in fuzzed_args if (not arg.startswith('-o') and not arg.startswith(
        '-I') and not arg.startswith('-L') and not arg.startswith('-c'))]  # Remove -o and -I arguments

    # Create a new list of arguments excluding the randomly selected ones
    final_args = [arg for arg in args_to_fuzz if arg not in fuzzed_args]

    # Build the new command line
    new_command_line = []
    new_command_line.append(command_line['compiler'])
    if command_line['source_file']:
        new_command_line.extend(command_line['source_file'])
    new_command_line.extend(final_args)
    command_to_run = []
    for arg in new_command_line:
        if ' ' in arg:
            command_to_run.extend(arg.split())
        else:
            command_to_run.append(arg)

    # Execute the new command line
    try:
        result = subprocess.run(
            command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_to_json("remove", fuzzed_args, original_command,
                    command_to_run, "SUCCESS", result.stdout.decode().strip())
        subprocess.run(original_command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        # print(error_message.strip())
        log_to_json("remove", fuzzed_args, original_command,
                    command_to_run, "ERROR", error_message)
        try:
            subprocess.run(original_command, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e1:
            print('Wrong Command!')
            print(command_to_run)
            print(e1.stderr.decode().strip())


def fuzz_reordering(command_line):
    # print("Reordering")
    args_to_fuzz = command_line['other_params']

    # Randomly shuffle the arguments
    random.shuffle(args_to_fuzz)

    # Build the new command line
    new_command_line = []
    new_command_line.append(command_line['compiler'])
    if command_line['source_file']:
        new_command_line.extend(command_line['source_file'])
    new_command_line.extend(args_to_fuzz)
    command_to_run = []
    for arg in new_command_line:
        if ' ' in arg:
            command_to_run.extend(arg.split())
        else:
            command_to_run.append(arg)
    # Execute the new command line
    try:
        result = subprocess.run(
            command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # print(result.stdout.decode().strip())
        print("Wrapper is 1running")
        log_to_json("reorder", None, original_command, command_to_run,
                    "SUCCESS", result.stdout.decode().strip())
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        # print(error_message.strip())
        print("Wrapper is 1111re-running")
        log_to_json("reorder", None, original_command,
                    command_to_run, "ERROR", error_message)
        try:
            # print(command)
            subprocess.run(original_command, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e1:
            print("Wrapper is 2222re-running")
            print('Wrong Command!')
            print(command_to_run)
            print(e1.stderr.decode().strip())


# original_line, modified_line, error, node_kind = remove_parentheses(source_files, original_command, command_line)

def remove_parentheses(filename, original_command, command_line):
    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()

    processed_offsets = set()

    for node in tu.cursor.walk_preorder():
        # print(parentheses.get_ast_string(node))
        # in [clang.cindex.CursorKind.FOR_STMT, clang.cindex.CursorKind.WHILE_STMT, clang.cindex.CursorKind.IF_STMT]:
        if node.kind:
            start = node.extent.start.offset
            end = node.extent.end.offset
            node_content = content[start:end]

            # Find all parentheses pairs
            paren_pairs = []
            stack = []
            for i, char in enumerate(node_content):
                if char == '(':
                    stack.append(i)
                elif char == ')':
                    if stack:
                        paren_start = stack.pop()
                        paren_pairs.append((paren_start, i))

            # Sort parentheses pairs by their starting position
            paren_pairs.sort(key=lambda x: x[0])
            for open_paren, close_paren in paren_pairs:
                # print(f"Open Parenthesis: {open_paren}, Close Parenthesis: {close_paren}")
                # Skip if this pair has already been processed
                if (start + open_paren) in processed_offsets or (start + close_paren) in processed_offsets:
                    continue
                if parentheses.find_node_at_offset(node, start + open_paren).kind == clang.cindex.CursorKind.FOR_STMT:
                    continue
                original_line = parentheses.get_line_at_offset(
                    content, start + open_paren)
                print(f"Original line: {original_line.strip()}")

                # Find the specific AST node for the opening parenthesis
                print(start + open_paren)
                open_paren_node = parentheses.find_node_at_offset(
                    node, start + open_paren)
                node_kind = open_paren_node.kind

                print(f"Parenthesis node kind: {open_paren_node.kind}")

                modified_content = content[:start + open_paren] + content[start +
                                                                          open_paren + 1:start + close_paren] + content[start + close_paren + 1:]
                modified_line = parentheses.get_line_at_offset(
                    modified_content, start + open_paren)
                print(f"Modified line: {modified_line.strip()}")
                print()
                modified_filename = os.path.splitext(
                    filename)[0] + '_modified' + os.path.splitext(filename)[1]
                with open(modified_filename, 'w') as file:
                    file.write(modified_content)

                command_to_run = original_command.copy()
                for idx, element in enumerate(command_to_run):
                    if element == filename:
                        command_to_run[idx] = modified_filename
                        break

                try:
                    result = subprocess.run(
                        command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    log_to_json('remove_parentheses', original_line, modified_line,
                                node_kind, "SUCCESS", result.stdout.decode().strip())
                    subprocess.run(original_command, check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except subprocess.CalledProcessError as e:
                    error_message = e.stderr.decode()
                    log_to_json('remove_parentheses', original_line,
                                modified_line, node_kind, "ERROR", error_message)
                    try:
                        subprocess.run(
                            original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    except subprocess.CalledProcessError as e1:
                        print('Wrong Command!')
                        print(original_command)
                        print(e1.stderr.decode().strip())

                # Mark these parentheses as processed
                processed_offsets.add(start + open_paren)
                processed_offsets.add(start + close_paren)

    # print(f"Error: No suitable parentheses pairs found.")
    return None, None


def fuzz_remove_parentheses(command_line):

    source_files = command_line['source_file']
    for source_file in source_files:
        # print("11111")
        remove_parentheses(source_file, original_command, command_line)


def parse_clang_command(command_line):
    args = command_line
    # Initialize components
    if "++" in args[0]:
        compiler = 'clang++'
    else:
        compiler = 'clang'
    source_file = []
    other_params = []

    # Identify components
    i = 1  # Skip the compiler
    while i < len(args):
        arg = args[i]
        if recognize_source_file_extension(arg):
            source_file.append(arg)
        elif arg in Arg_With_Attached:
            assert i + 1 < len(args), f"Missing argument for {arg}"
            arg += ' ' + args[i + 1]
            # args[i + 1] = ''  # Clear the next argument
            other_params.append(arg)
            i += 1  # Increment to move to the next argument
        else:
            other_params.append(arg)
        i += 1  # Increment to move to the next argument

    return {
        'compiler': compiler,
        'source_file': source_file,
        'other_params': other_params
    }


# Example usage
if __name__ == "__main__":

    command = sys.argv
    original_command = command.copy()

    if 'wrapper' not in command[0]:
        subprocess.run(command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if "++" in command[0]:
        original_command[0] = 'clang++'
    else:
        original_command[0] = 'clang'

    parse_fuzz_mode()

    if fuzz_modes[0] == 'none' or not fuzz_modes:
        subprocess.run(original_command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    parsed_command = parse_clang_command(command)
    mode = random.choice(fuzz_modes)
    if mode == 'reorder':
        fuzz_reordering(parsed_command)
    elif mode == 'remove':
        fuzz_remove(parsed_command)
    elif mode == 'remove_parentheses':
        fuzz_remove_parentheses(parsed_command)
