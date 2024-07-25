#!/p/lustre2/shan4/anaconda3/bin/python

"""This script wraps the compiler, fuzzes the command line arguments, and executes the compiler with the fuzzed arguments."""

import subprocess
import sys
import random
import os
from utils import log_to_json

import clang.cindex
import code_modification.parentheses as parentheses
import code_modification.symbol as symbol
import code_modification.asterisk as asterisk
from collections import defaultdict


RECOGNIZED_SOURCE_FILE_EXTENSIONS = ['.c', '.cpp', '.cxx', '.cc', '.c++']
Arg_With_Attached = ['-Xlinker', '-MF', '-MT', '-isystem', '-o', '-D']
mode_list = ['reorder', 'remove', 'replace', 'insert', 'remove_parentheses', 'replace_colon_with_semicolon', 'add_asterisk_to_variables']
Arg_Not_Removed = ['-o', '-I']
log_file_path = '/p/lustre2/shan4/Fuzzlang/log_llvm_removept2.json'
fuzz_modes = ['none']
remove_level = 1
command = []
original_command = []
if not clang.cindex.Config.library_file:
    clang.cindex.Config.set_library_file(
        '/p/lustre2/shan4/llvm-trunk/lib/libclang.so')
index = clang.cindex.Index.create()

# Fuzz the command line arguments based on the FUZZ_MODE environment
# Fuzz mode for args:
#  1 - reorder: Randomly reorder the arguments
#  2 - remove: Randomly remove a subset of the arguments
#  3 - replace: Randomly replace a subset of the arguments
#  4 - insert: Randomly insert a subset of the arguments
# Remove level:
#  1 - low: Remove 1 of the arguments
#  2 - medium: Remove 1 to 1/2 of the arguments
#  3 - high: Remove 1/2 to all of the arguments

# Fuzz mode for source code:
#  1 - remove_parentheses: Remove parentheses from the source code
#  2 - replace_colon_with_semicolon: Replace colon with semicolon in the source code
#  3 - add_asterisk_to_variables: Add asterisk to variables in the source code

def parse_fuzz_mode():
    global remove_level, fuzz_modes
    # Get the FUZZ_MODE environment variable
    fuzz_mode = os.getenv('FUZZ_MODE', '')
    if fuzz_mode == '' or fuzz_mode == 'none':
        fuzz_modes = ['none']
        return
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
        if mode in mode_list:
            fuzz_modes.append(mode)
        else:
            print(f"Invalid fuzz mode: {mode}")
    if remove_level:
        try:
            remove_level = int(remove_level)
        except ValueError:
            print(f"Invalid remove level: {remove_level}")
            print("Remove level must be an integer value between 1 and 3")


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
                    command_to_run, "SUCCESS", result.stdout.decode().strip(), log_file_path)
        subprocess.run(original_command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        # print(error_message.strip())
        log_to_json("remove", fuzzed_args, original_command,
                    command_to_run, "ERROR", error_message, log_file_path)
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
                    "SUCCESS", result.stdout.decode().strip(), log_file_path)
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode()
        log_to_json("reorder", None, original_command,
                    command_to_run, "ERROR", error_message, log_file_path)
        try:
            # print(command)
            subprocess.run(original_command, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e1:
            print('Wrong Command!')
            print(command_to_run)
            print(e1.stderr.decode().strip())


def fuzz_remove_parentheses(command_line):
    source_files = command_line['source_file']
    for source_file in source_files:
        parentheses.remove_parentheses(
            source_file, original_command, command_line, log_file_path)

def fuzz_replace_colon_with_semicolon(command_line):
    source_files = command_line['source_file']
    for source_file in source_files:
        symbol.replace_colon_with_semicolon(
            source_file, original_command, command_line, log_file_path)
        
def fuzz_add_asterisk_to_variables(command_line):
    source_files = command_line['source_file']
    for source_file in source_files:
        asterisk.add_asterisk_to_variables(
            source_file, original_command, command_line, log_file_path)

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
    elif mode == 'replace_colon_with_semicolon':
        fuzz_replace_colon_with_semicolon(parsed_command)
    elif mode == 'add_asterisk_to_variables':
        fuzz_add_asterisk_to_variables(parsed_command)
