import clang.cindex
import random
import subprocess
import os

from utils import log_to_json, get_line_at_offset

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
        # print("AST for this line:")
        # print(get_ast_string(node))
        return node
    return None

def find_node_at_offset1(node, target_offset):
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
    modified_filename = os.path.splitext(filename)[0] + '_modified' + os.path.splitext(filename)[1]
    with open(modified_filename, 'w') as file:
        file.write(content)
    return modified_filename

def remove_parentheses(filename, original_command, command_line, log_file_path):
    index = clang.cindex.Index.create()
    tu = index.parse(filename)

    with open(filename, 'r') as file:
        content = file.read()

    processed_offsets = set()

    for node in tu.cursor.walk_preorder():
        # print(get_ast_string(node))
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
                if find_node_at_offset(node, start + open_paren).kind == clang.cindex.CursorKind.FOR_STMT:
                    continue
                # if random.random() > 0.1:
                #     processed_offsets.add(start + open_paren)
                #     processed_offsets.add(start + close_paren)
                #     continue
                original_line = get_line_at_offset(
                    content, start + open_paren)
                # if start + open_paren not in [118,150,182]:
                #     continue
                print(f"Original line: {original_line.strip()}")

                # Find the specific AST node for the opening parenthesis
                print(start + open_paren)
                
                open_paren_node = find_node_at_offset1(
                    node, start + open_paren)
                node_kind = open_paren_node.kind

                print(f"Parenthesis node kind: {open_paren_node.kind}")

                modified_content = content[:start + open_paren] + content[start +
                                                                          open_paren + 1:start + close_paren] + content[start + close_paren + 1:]
                modified_line = get_line_at_offset(
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
                                node_kind, "SUCCESS", result.stdout.decode().strip(), log_file_path)
                except subprocess.CalledProcessError as e:
                    error_message = e.stderr.decode()
                    log_to_json('remove_parentheses', original_line,
                                modified_line, node_kind, "ERROR", error_message, log_file_path)

                # Mark these parentheses as processed
                processed_offsets.add(start + open_paren)
                processed_offsets.add(start + close_paren)
    try:
        subprocess.run(original_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e1:
        print('Wrong Command!')
        print(original_command)
        print(e1.stderr.decode().strip())

    # print(f"Error: No suitable parentheses pairs found.")
    return None, None

# original_line, modified_line, error, node_kind = remove_control_parentheses(source_files, original_command, command_line)
# cpp_file = 'tmp.cpp'
# target_index = 2 #int(input("Enter the index of the parentheses pair to remove: "))
# modified_content, modified_line = remove_control_parentheses(cpp_file, target_index)

# if modified_content:
#     modified_file = create_modified_file(cpp_file, modified_content)