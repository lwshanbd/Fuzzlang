import clang.cindex
import random
import subprocess
import os
import subprocess
import difflib
import json
import tempfile
from utils import log_to_json, get_line_at_offset, get_ast_string, find_node_at_offset

fuzz_modes = {
        ':': 'remove_colon',
        ';': 'remove_semicolon',
        ',': 'remove_comma',
        '.': 'remove_dot',
        '*': 'remove_asterisk',
        '&': 'remove_ampersand',
        '!': 'remove_exclamation',
        '=': 'remove_equal',
        '+': 'remove_plus',
        '-': 'remove_minus',
        '/': 'remove_slash',
        '%': 'remove_percent',
        '<': 'remove_less',
        '>': 'remove_greater',
        '^': 'remove_caret',
        '|': 'remove_pipe',
        '~': 'remove_tilde',
        '?': 'remove_question',
        #'#': 'remove_hash'
}

def create_modified_file(filename, content):
    modified_filename = os.path.splitext(
        filename)[0] + '_modified' + os.path.splitext(filename)[1]
    with open(modified_filename, 'w') as file:
        file.write(content)
    return modified_filename


def get_fuzz_mode(symbol):
    return fuzz_modes.get(symbol, 'unknown_symbol')

def all_running(filename, original_command, log_file_path, replace_mode='1'):
    for mode in fuzz_modes:
        remove_single_symbol(filename, mode, original_command, log_file_path, replace_mode)

def remove_single_symbol(filename, symbol, original_command, log_file_path, remove_mode='1'):
    fuzz_mode = get_fuzz_mode(symbol)
    if fuzz_mode == 'unknown_symbol':
        raise ValueError(f"Unknown symbol: {symbol}")

    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()
    processed_offsets = set()
    
    symbols = []

    for node in tu.cursor.walk_preorder():
        start = node.extent.start.offset
        end = node.extent.end.offset
        node_content = content[start:end]

        # Find all symbols
        
        for i, char in enumerate(node_content):
            if char == symbol:
                symbols.append((i, node))

    # Sort parentheses pairs by their starting position
    symbols.sort(key=lambda x: x[0])

    if remove_mode != 'all':
        remove_number = int(remove_mode)
        if remove_number > len(symbols):
            remove_number = len(symbols)
        symbols = random.sample(symbols, remove_number)
            
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

        print(start + symbol)

        symbol_node = find_node_at_offset(node, start + symbol)
        node_kind = symbol_node.kind

        print(f"Node kind: {symbol_node.kind}")

        modified_content = content[:start + symbol] + content[start + symbol + 1:]
        modified_line = get_line_at_offset(
            modified_content, start + symbol)
        print(f"Modified line: {modified_line.strip()}\n")

        # modified_filename = os.path.splitext(
        #     filename)[0] + '_modified' + os.path.splitext(filename)[1]
        # with open(modified_filename, 'w') as file:
        #     file.write(modified_content)
        
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
