#!/usr/bin/python

import subprocess
import sys
import random
import os
from typing import List, Dict
import clang.cindex
from collections import defaultdict

# Import other modules (assuming they exist in the same directory)
import code_modification.parentheses as parentheses
import code_modification.symbol as symbol
import code_modification.asterisk as asterisk
import code_modification.replace as symbol_replace
import code_modification.remove_single as remove_single
import code_modification.lambdafunc as lambda_modification
from utils import log_to_json

class FuzzlangWrapper:
    RECOGNIZED_SOURCE_FILE_EXTENSIONS = ['.c', '.cpp', '.cxx', '.cc', '.c++']
    ARG_WITH_ATTACHED = ['-Xlinker', '-MF', '-MT', '-isystem', '-o', '-D']
    ARG_NOT_REMOVED = ['-o', '-I', '-L', '-c']
    MODE_LIST = ['argsremove', 'argsreorder', 'replace_all', 'remove_single', 
                 'remove_parentheses', 'replace_colon_with_semicolon', 'add_asterisk_to_variables','lambda_captures']
    
    def __init__(self):
        self.log_file_path = './tmp.json'
        self.fuzz_modes = ['none']
        self.remove_level = 1
        self.command = []
        self.original_command = []
        self.parsed_command = {}

        if not clang.cindex.Config.library_file:
            clang.cindex.Config.set_library_file('/lustre/software/llvm/18.1.1/lib/libclang.so')
        self.index = clang.cindex.Index.create()

    def parse_fuzz_mode(self):
        fuzz_mode = os.getenv('FUZZ_MODE', '')
        if fuzz_mode == '' or fuzz_mode == 'none':
            self.fuzz_modes = ['none']
            return

        self.remove_level = int(os.getenv('REMOVE_LEVEL', '1'))
        
        for sep in [',', '&']:
            fuzz_mode = fuzz_mode.replace(sep, ' ')
        
        modes = list(set([mode.strip() for mode in fuzz_mode.split() if mode.strip()]))
        
        if modes:
            self.fuzz_modes = [mode for mode in modes if mode in self.MODE_LIST]

    def recognize_source_file_extension(self, file_path: str) -> bool:
        return any(file_path.endswith(ext) for ext in self.RECOGNIZED_SOURCE_FILE_EXTENSIONS)

    def parse_clang_command(self, command_line: List[str]) -> Dict[str, List[str]]:
        compiler = 'clang++' if '++' in command_line[0] else 'clang'
        source_file = []
        other_params = []

        i = 1
        while i < len(command_line):
            arg = command_line[i]
            if self.recognize_source_file_extension(arg):
                source_file.append(arg)
            elif arg in self.ARG_WITH_ATTACHED:
                assert i + 1 < len(command_line), f"Missing argument for {arg}"
                arg += ' ' + command_line[i + 1]
                other_params.append(arg)
                i += 1
            else:
                other_params.append(arg)
            i += 1

        return {
            'compiler': compiler,
            'source_file': source_file, 
            'other_params': other_params
        }

    def argsfuzz(self, mode):
        args_to_fuzz = self.parsed_command['other_params']
        if not args_to_fuzz:
            return

        if mode == 'argsreorder':
            random.shuffle(args_to_fuzz)
            fuzz_type = "reorder"
            fuzzed_args = None
        elif mode == 'argsremove':
            if self.remove_level == 1:
                num_to_remove = 1
            elif self.remove_level == 2:
                num_to_remove = random.randint(1, int(len(args_to_fuzz)/2+1))
            elif self.remove_level == 3:
                num_to_remove = random.randint(int(len(args_to_fuzz)/2), len(args_to_fuzz)-1)
            else:
                num_to_remove = random.randint(1, len(args_to_fuzz)-1)

            fuzzed_args = random.sample(args_to_fuzz, num_to_remove)
            fuzzed_args = [arg for arg in fuzzed_args if not any(arg.startswith(prefix) for prefix in self.ARG_NOT_REMOVED)]
            args_to_fuzz = [arg for arg in args_to_fuzz if arg not in fuzzed_args]
            fuzz_type = "remove"
        else:
            return  # Invalid mode

        new_command_line = [self.parsed_command['compiler']] + self.parsed_command['source_file'] + args_to_fuzz
        command_to_run = [item for arg in new_command_line for item in arg.split()]

        self.run_command(command_to_run, fuzz_type, fuzzed_args)

    def fuzz_source_code(self, fuzz_type):
        for source_file in self.parsed_command['source_file']:
            if fuzz_type == 'remove_parentheses':
                parentheses.remove_parentheses(source_file, self.original_command, self.parsed_command, self.log_file_path)
            elif fuzz_type == 'replace_colon_with_semicolon':
                symbol.replace_colon_with_semicolon(source_file, self.original_command, self.parsed_command, self.log_file_path)
            elif fuzz_type == 'add_asterisk_to_variables':
                asterisk.add_asterisk_to_variables(source_file, self.original_command, self.parsed_command, self.log_file_path)
            elif fuzz_type == 'replace_all':
                symbol_replace.all_running(source_file, self.original_command, self.log_file_path)
            elif fuzz_type == 'remove_single':
                remove_single.all_running(source_file, self.original_command, self.log_file_path)
            elif fuzz_type == 'lambda_captures':
                lambda_modification.all_running(source_file, self.original_command, self.log_file_path)

    def run_command(self, command_to_run, fuzz_type, fuzzed_args=None):
        try:
            result = subprocess.run(command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log_to_json(fuzz_type, fuzzed_args, self.original_command, command_to_run, "SUCCESS", result.stdout.decode().strip(), self.log_file_path)
            subprocess.run(self.original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            error_message = e.stderr.decode()
            log_to_json(fuzz_type, fuzzed_args, self.original_command, command_to_run, "ERROR", error_message, self.log_file_path)
            try:
                subprocess.run(self.original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e1:
                print('Wrong Command!')
                print(command_to_run)
                print(e1.stderr.decode().strip())

    def run(self):
        self.command = sys.argv
        self.original_command = self.command.copy()

        if 'wrapper' not in self.command[0]:
            subprocess.run(self.command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return

        self.original_command[0] = 'clang++' if '++' in self.command[0] else 'clang'

        self.parse_fuzz_mode()

        if self.fuzz_modes[0] == 'none' or not self.fuzz_modes:
            subprocess.run(self.original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return

        self.parsed_command = self.parse_clang_command(self.command)
        mode = random.choice(self.fuzz_modes)

        if mode in ['argsremove', 'argsreorder']:
            self.argsfuzz(mode)
        elif mode in ['remove_parentheses', 'replace_colon_with_semicolon', 'add_asterisk_to_variables', 'replace_all', 'remove_single', 'lambda_captures']:
            self.fuzz_source_code(mode)

        try:
            subprocess.run(self.original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e1:
            print('Wrong Command!')
            print(self.original_command)
            print(e1.stderr.decode().strip())

if __name__ == "__main__":
    wrapper = FuzzlangWrapper()
    wrapper.run()