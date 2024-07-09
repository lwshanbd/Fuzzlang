import clang.cindex
import os

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
    modified_filename = os.path.splitext(filename)[0] + '_modified' + os.path.splitext(filename)[1]
    with open(modified_filename, 'w') as file:
        file.write(content)
    return modified_filename


# original_line, modified_line, error, node_kind = remove_control_parentheses(source_files, original_command, command_line)
# cpp_file = 'tmp.cpp'
# target_index = 2 #int(input("Enter the index of the parentheses pair to remove: "))
# modified_content, modified_line = remove_control_parentheses(cpp_file, target_index)

# if modified_content:
#     modified_file = create_modified_file(cpp_file, modified_content)