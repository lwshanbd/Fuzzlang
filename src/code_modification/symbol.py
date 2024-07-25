import clang.cindex
import random
import subprocess
import os
import subprocess
import difflib
import json
from utils import log_to_json, get_line_at_offset


import clang.cindex


from typing import List, Dict, Any


def node_to_dict(node: clang.cindex.Cursor) -> Dict[str, Any]:
    return {
        'kind': node.kind.name,
        'spelling': node.spelling,
        'location': f"{node.location.file}:{node.location.line}:{node.location.column}" if node.location.file else "Unknown",
        'type': node.type.spelling,
    }


def get_ast(node: clang.cindex.Cursor) -> Dict[str, Any]:
    result = node_to_dict(node)
    result['children'] = [get_ast(child) for child in node.get_children()]
    return result


def compare_asts(original: Dict[str, Any], modified: Dict[str, Any]) -> List[Dict[str, str]]:
    changes = []

    modified['spelling'] = modified['spelling'].replace('modified1_', '')
    modified['location'] = modified['location'].replace('modified1_', '')
    if original['kind'] != modified['kind']:
        changes.append({
            'type': 'node_changed',
            'details': f"Node kind changed from '{original['kind']}' to '{modified['kind']}'"
        })

    if original['spelling'] != modified['spelling']:

        changes.append({
            'type': 'name_changed',
            'details': f"Node spelling changed from '{original['spelling']}' to '{modified['spelling']}'"
        })

    if original['type'] != modified['type']:
        changes.append({
            'type': 'type_changed',
            'details': f"Node type changed from '{original['type']}' to '{modified['type']}'"
        })

    if original['location'] != modified['location']:
        changes.append({
            'type': 'position_changed',
            'details': f"Node position changed from {original['location']} to {modified['location']}"
        })

    if len(original['children']) != len(modified['children']):
        changes.append({
            'type': 'structure_change',
            'details': f"{original['kind']} children count changed from {len(original['children'])} to {len(modified['children'])}"
        })

    for orig_child, mod_child in zip(original['children'], modified['children']):
        changes.extend(compare_asts(orig_child, mod_child))

    for child in modified['children'][len(original['children']):]:
        changes.append({
            'type': 'node_added',
            'details': f"New {child['kind']} '{child['spelling']}' added at {child['location']}"
        })

    for child in original['children'][len(modified['children']):]:
        changes.append({
            'type': 'node_removed',
            'details': f"{child['kind']} '{child['spelling']}' removed from {child['location']}"
        })

    return changes


def replace_colon_with_semicolon(filename, original_command, command_line, log_file_path):
    index = clang.cindex.Index.create()
    original_tu = index.parse(filename)
    original_ast = get_ast(original_tu.cursor)

    with open(filename, 'r') as file:
        content = file.read()

    colon_positions = [i for i, char in enumerate(content) if char == ':']

    for position in colon_positions:
        original_line = content.splitlines()[content[:position].count('\n')]
        modified_content = content[:position] + ';' + content[position + 1:]
        modified_line = modified_content.splitlines(
        )[modified_content[:position].count('\n')]

        modified_filename = f"modified1_{filename}"
        with open(modified_filename, 'w') as file:
            file.write(modified_content)

        modified_tu = index.parse(modified_filename)
        modified_ast = get_ast(modified_tu.cursor)

        ast_changes = compare_asts(original_ast, modified_ast)

        command_to_run = [cmd.replace(filename, modified_filename)
                          for cmd in original_command]
        try:
            result = subprocess.run(
                command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            compilation_result = "SUCCESS"
            error_message = ""
        except subprocess.CalledProcessError as e:
            compilation_result = "ERROR"
            error_message = e.stderr.decode()

        log_data = {
            'original_line': original_line.strip(),
            'modified_line': modified_line.strip(),
            'position': position,
            'ast_changes': ast_changes,
            'compilation_result': compilation_result,
            'error_message': error_message
        }

        with open(log_file_path, 'a') as log_file:
            json.dump(log_data, log_file)
            log_file.write('\n')

        print(f"Processed colon at position {position}")

    return None, None


def replace_symbol(filename, original_command, command_line, log_file_path, original_symbol, new_symbol):
    index = clang.cindex.Index.create()
    original_tu = index.parse(filename)
    original_ast = get_ast(original_tu.cursor)

    with open(filename, 'r') as file:
        content = file.read()

    symbol_positions = [i for i, char in enumerate(
        content) if char == original_symbol]

    for position in symbol_positions:
        original_line = content.splitlines()[content[:position].count('\n')]
        modified_content = content[:position] + \
            new_symbol + content[position + 1:]
        modified_line = modified_content.splitlines(
        )[modified_content[:position].count('\n')]

        modified_filename = f"{filename}_modified.c"
        with open(modified_filename, 'w') as file:
            file.write(modified_content)

        modified_tu = index.parse(modified_filename)
        modified_ast = get_ast(modified_tu.cursor)

        ast_changes = compare_asts(original_ast, modified_ast)

        command_to_run = [cmd.replace(filename, modified_filename)
                          for cmd in original_command]
        try:
            result = subprocess.run(
                command_to_run, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            compilation_result = "SUCCESS"
            error_message = ""
        except subprocess.CalledProcessError as e:
            compilation_result = "ERROR"
            error_message = e.stderr.decode()

        log_data = {
            'original_line': original_line.strip(),
            'modified_line': modified_line.strip(),
            'position': position,
            'ast_changes': ast_changes,
            'compilation_result': compilation_result,
            'error_message': error_message
        }

        with open(log_file_path, 'a') as log_file:
            json.dump(log_data, log_file)
            log_file.write('\n')

        print(f"Processed colon at position {position}")

    return None, None
