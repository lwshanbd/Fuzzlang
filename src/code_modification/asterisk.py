import clang.cindex
import random
import subprocess
import os
import subprocess
import difflib
import json
from utils import log_to_json, get_line_at_offset


def should_add_asterisk(node):
    return (node.kind in [clang.cindex.CursorKind.VAR_DECL,
                          clang.cindex.CursorKind.PARM_DECL,
                          clang.cindex.CursorKind.FIELD_DECL,
                          clang.cindex.CursorKind.DECL_REF_EXPR] and
            node.type.kind != clang.cindex.TypeKind.POINTER)


def find_identifier_token(node):
    tokens = list(node.get_tokens())
    for token in tokens:
        if token.kind == clang.cindex.TokenKind.IDENTIFIER:
            return token
    return None


def add_asterisk_to_variables(filename, original_command, command_line, log_file_path):
    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()
    modified_filename = ''
    processed_offsets = set()
    for node in tu.cursor.walk_preorder():
        if str(node.location.file) != filename:
            continue
        if should_add_asterisk(node):
            start = node.extent.start.offset
            end = node.extent.end.offset
            
            referenced = node.referenced
            # print(f"Referenced: {referenced.spelling}")
            # print(f"Referenced: {referenced.kind}")
            # For declarations, find the position of the variable name
            if node.kind in [clang.cindex.CursorKind.VAR_DECL, clang.cindex.CursorKind.PARM_DECL, clang.cindex.CursorKind.FIELD_DECL]:
                identifier_token = find_identifier_token(
                    node)
                if identifier_token is not None:
                    print(f"Identifier token: {identifier_token.spelling}")
                    start = identifier_token.extent.start.offset
                for child in node.get_children():
                    if child.kind == clang.cindex.CursorKind.TYPE_REF:
                        start = child.extent.end.offset
                        break

            # Skip if this position has already been processed
            if referenced is not None:
                if referenced.kind == clang.cindex.CursorKind.OVERLOADED_DECL_REF:
                    continue
                print(f"Referenced: {referenced.spelling}")
                print(f"Referenced: {referenced.kind}")
            if start in processed_offsets:
                continue
            

            original_line = get_line_at_offset(content, start)
            print(f"Original line: {original_line.strip()}")
            print(f"Start: {start}")
            print(f"node location: {node.location.file}")
            print(f"node spelling: {node.spelling}")
            # Add asterisk before variable name or reference
            modified_content = content[:start] + '*' + content[start:]
            modified_line = get_line_at_offset(modified_content, start)
            print(f"Modified line: {modified_line.strip()}")
            print(f"Node kind: {node.kind}")
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
                log_to_json('add_asterisk', original_line, modified_line,
                            str(node.kind), "SUCCESS", result.stdout.decode().strip(), log_file_path)
            except subprocess.CalledProcessError as e:
                error_message = e.stderr.decode()
                log_to_json('add_asterisk', original_line,
                            modified_line, str(node.kind), "ERROR", error_message, log_file_path)

            # Mark this position as processed
            processed_offsets.add(start)
    if os.path.exists(modified_filename):
        os.remove(modified_filename)
        
    try:
        subprocess.run(original_command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e1:
        print('Wrong Command!')
        print(original_command)
        print(e1.stderr.decode().strip())

    return None, None
