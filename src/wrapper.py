#!/usr/bin/python

"""This script wraps the compiler, fuzzes the command line arguments, and executes the compiler with the fuzzed arguments."""

import subprocess
import sys
import random

RECOGNIZED_SOURCE_FILE_EXTENSIONS = ['.c', '.cpp', '.cxx', '.cc', '.c++']


def recognize_source_file_extension(file_path):
    for recognized_extension in RECOGNIZED_SOURCE_FILE_EXTENSIONS:
        if file_path.endswith(recognized_extension):
            return True

    return False


def fuzz_clang_runner(command_line):

    args_to_fuzz = command_line['other_params']

    # Randomly determine the number of arguments to remove
    num_to_remove = random.randint(0, len(args_to_fuzz))
    fuzzed_args = random.sample(args_to_fuzz, num_to_remove)

    # Create a new list of arguments excluding the randomly selected ones
    other_params = [arg for arg in args_to_fuzz if arg not in fuzzed_args]

    # Build the new command line
    new_command_line = []
    new_command_line.append(command_line['compiler'])
    new_command_line.extend(command_line['source_file'])
    if command_line['output_flag']:
        new_command_line.append(command_line['output_flag'])
        new_command_line.append(command_line['output_file'])
    new_command_line.extend(other_params)

    # Execute the new command line
    try:
        result = subprocess.run(
            new_command_line, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("SUCCESS:", " ".join(new_command_line))
        print("Output:", result.stdout.decode())
    except subprocess.CalledProcessError as e:
        print("FAILURE:", " ".join(new_command_line))
        print("Error:", e.stderr.decode())


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
    print("Command Line: ", command)
    parsed_command = parse_clang_command(command)
    print("Parsed Command Components:")
    print("Compiler: ", parsed_command['compiler'])
    print("Source File: ", parsed_command['source_file'])
    print("Output Flag: ", parsed_command['output_flag'])
    print("Output File: ", parsed_command['output_file'])
    print("Other Parameters: ", ' '.join(parsed_command['other_params']))
    fuzz_clang_runner(parsed_command)
