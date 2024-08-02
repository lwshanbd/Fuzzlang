import clang.cindex
import random
import subprocess
import os
import subprocess
import difflib
import json
from utils import log_to_json, get_line_at_offset, get_ast_string, find_node_at_offset


def create_modified_file(filename, content):
    modified_filename = os.path.splitext(
        filename)[0] + '_modified' + os.path.splitext(filename)[1]
    with open(modified_filename, 'w') as file:
        file.write(content)
    return modified_filename


def get_fuzz_mode(symbol_source, symbol_target):
    fuzz_modes = {
        ":t::": "replace_colon_with_double_colon",
        "::t:": "replace_double_colon_with_colon",
        ":t;": "replace_colon_with_semicolon",
        ":t,": "replace_colon_with_comma",
        ";t:": "replace_semicolon_with_colon",
        ";t,": "replace_semicolon_with_comma",
        ",t:": "replace_comma_with_colon",
        "=t==": "replace_equal_with_double_equal",
        "==t=": "replace_double_equal_with_equal",
    }

    return fuzz_modes.get(f"{symbol_source}t{symbol_target}", 'unknown_symbol')

def replace_single_symbol(filename, symbol_source, symbol_target, original_command, log_file_path, replace_mode='1'):
    fuzz_mode = get_fuzz_mode(symbol_source, symbol_target)
    if fuzz_mode == 'unknown_symbol':
        raise ValueError(f"Unknown symbol: {symbol_source}, {symbol_target}")

    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()

    processed_offsets = set()

    for node in tu.cursor.walk_preorder():
        start = node.extent.start.offset
        end = node.extent.end.offset
        node_content = content[start:end]

        # Find all symbols
        symbols = []
        for i, char in enumerate(node_content):
            if char == symbol:
                symbols.append(i)

        # Sort symbols by their starting position
        symbols.sort(key=lambda x: x[0])

        if replace_mode != 'all':
            replace_number = int(replace_mode)
            if replace_number > len(symbols):
                replace_number = len(symbols)
            symbols = random.sample(symbols, replace_number)

        for symbol in symbols:
            # Skip if this pair has already been processed
            if (start + symbol) in processed_offsets:
                continue

            original_line = get_line_at_offset(
                content, start + symbol)
            print(f"Original line: {original_line.strip()}")

            print(start + symbol)

            symbol_node = find_node_at_offset(node, start + symbol)
            node_kind = symbol_node.kind

            print(f"Node kind: {symbol_node.kind}")

            modified_content = content[:start + symbol] + symbol_target + content[start + symbol + 1:]
            modified_line = get_line_at_offset(
                modified_content, start + symbol)
            print(f"Modified line: {modified_line.strip()}\n")

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
                log_to_json(fuzz_mode, original_line, modified_line,
                            node_kind, "SUCCESS", result.stdout.decode().strip(), log_file_path)
            except subprocess.CalledProcessError as e:
                error_message = e.stderr.decode()
                log_to_json(fuzz_mode, original_line,
                            modified_line, node_kind, "ERROR", error_message, log_file_path)

            # Mark this symbol as processed
            processed_offsets.add(start + symbol)
    try:
        subprocess.run(original_command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e1:
        print('Wrong Command!')
        print(original_command)
        print(e1.stderr.decode().strip())

    return None, None
