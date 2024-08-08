import clang.cindex
import random
import subprocess
import os
import re
import subprocess
import difflib
import json
import tempfile
from utils import log_to_json, get_line_at_offset, get_ast_string, find_node_at_offset

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


def get_fuzz_mode(symbol_source, symbol_target):
    return fuzz_modes.get(f"{symbol_source}t{symbol_target}", 'unknown_symbol')


def all_running(filename, original_command, log_file_path, replace_mode='1'):
    for mode in fuzz_modes:
        symbol_source = mode.split('t')[0]
        symbol_target = mode.split('t')[1]
        replace_single_symbol(filename, symbol_source,
                              symbol_target, original_command, log_file_path)


def replace_single_symbol(filename, symbol_source, symbol_target, original_command, log_file_path, replace_mode='1'):

    fuzz_mode = get_fuzz_mode(symbol_source, symbol_target)
    print(f"Fuzz mode: {fuzz_mode}")
    if fuzz_mode == 'unknown_symbol':
        raise ValueError(f"Unknown symbol: {symbol_source}, {symbol_target}")

    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()

    processed_offsets = set()
    symbols = []
    for node in tu.cursor.walk_preorder():
        if str(node.location.file) != filename:
            continue
        start = node.extent.start.offset
        end = node.extent.end.offset
        node_content = content[start:end]

        # Find all symbols
        if 'replace_double' in fuzz_mode:
            for i, char in enumerate(node_content):
                if char == symbol_source[0]:
                    if i < len(node_content) - 1 and node_content[i+1] == symbol_source[1]:
                        symbols.append((i,node))
            continue
        for i, char in enumerate(node_content):
            if char == symbol_source:
                symbols.append((i,node))
        
    symbols.sort(key=lambda x: x[0])
    if replace_mode != 'all':
        replace_number = int(replace_mode)
        if replace_number > len(symbols):
            replace_number = len(symbols)
        symbols = random.sample(symbols, replace_number)
        
    for symbol_t in symbols:
        symbol = symbol_t[0]
        node = symbol_t[1]
        start = node.extent.start.offset
        end = node.extent.end.offset
        # Skip if this pair has already been processed
        if (start + symbol) in processed_offsets:
            continue

        original_line = get_line_at_offset(
            content, start + symbol)
        print(f"Original line: {original_line.strip()}")

        print(node.spelling)
        symbol_node = find_node_at_offset(node, start + symbol)
        node_kind = symbol_node.kind
        print(f"Node kind: {symbol_node.kind}")
        if 'replace_double' in fuzz_mode:
            modified_content = content[:start + symbol] + \
                symbol_target + content[start + symbol + 2:]
        else:
            modified_content = content[:start + symbol] + \
                symbol_target + content[start + symbol + 1:]
        modified_line = get_line_at_offset(
            modified_content, start + symbol)
        print(f"Modified line: {modified_line.strip()}\n")
        
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.cpp') as temp_file:
            # Write the modified content to the temporary file
            temp_file.write(modified_content)
            temp_file.flush()
            
            command_to_run = original_command.copy()
            for idx, element in enumerate(command_to_run):
                if element == filename:
                    command_to_run[idx] = temp_file.name
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


    return None, None
