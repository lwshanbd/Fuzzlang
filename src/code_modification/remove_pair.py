import clang.cindex
import random
import subprocess
import os
import subprocess
import difflib
import json
from utils import log_to_json, get_line_at_offset
import tempfile


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


def create_modified_file(filename, content):
    modified_filename = os.path.splitext(
        filename)[0] + '_modified' + os.path.splitext(filename)[1]
    with open(modified_filename, 'w') as file:
        file.write(content)
    return modified_filename


def remove_paired_symbol(filename, symbol, original_command, log_file_path, remove_mode='1'):
    if symbol == '(':
        paired_symbol = ')'
        fuzz_mode = 'remove_parentheses'
    elif symbol == '[':
        paired_symbol = ']'
        fuzz_mode = 'remove_brackets'
    elif symbol == '{':
        paired_symbol = '}'
        fuzz_mode = 'remove_braces'
    elif symbol == '<':
        paired_symbol = '>'
        fuzz_mode = 'remove_angle'
    else:
        raise ValueError(f"Unknown symbol: {symbol}")

    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()

    processed_offsets = set()

    for node in tu.cursor.walk_preorder():
        start = node.extent.start.offset
        end = node.extent.end.offset
        node_content = content[start:end]

        # Find all pairs
        symbol_pairs = []
        stack = []
        for i, char in enumerate(node_content):
            if char == symbol:
                stack.append(i)
            elif char == paired_symbol:
                if stack:
                    paren_start = stack.pop()
                    symbol_pairs.append(((paren_start, i),node))

        # Sort parentheses pairs by their starting position
    symbol_pairs.sort(key=lambda x: x[0][0])

    if remove_mode != 'all':
        remove_number = int(remove_mode)
        if remove_number > len(symbol_pairs):
            remove_number = len(symbol_pairs)
        symbol_pairs = random.sample(symbol_pairs, remove_number)

    for symbol_pair, node in symbol_pairs:
        left_symbol, right_symbol = symbol_pair
        start = node.extent.start.offset
        end = node.extent.end.offset
        node_content = content[start:end]
        # Skip if this pair has already been processed
        if (start + left_symbol) in processed_offsets or (start + right_symbol) in processed_offsets:
            continue
        
        original_line = get_line_at_offset(
            content, start + left_symbol)
        print(f"Original line: {original_line.strip()}")

        # Find the specific AST node for the opening parenthesis
        print(start + left_symbol)

        left_symbol_node = find_node_at_offset(
            node, start + left_symbol)
        node_kind = left_symbol_node.kind

        print(f"Node kind: {left_symbol_node.kind}")

        modified_content = content[:start + left_symbol] + content[start +
                                                                    left_symbol + 1:start + right_symbol] + content[start + right_symbol + 1:]
        modified_line = get_line_at_offset(
            modified_content, start + left_symbol)
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

            # Mark these symbol pairs as processed
            processed_offsets.add(start + left_symbol)
            processed_offsets.add(start + right_symbol)


    return None, None
