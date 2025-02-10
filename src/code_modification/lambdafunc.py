import clang.cindex
import sys
import random
import subprocess
import logging
import tempfile

from utils import log_to_json, get_line_at_offset, get_ast_string, find_node_at_offset

def all_running(filename, original_command, log_file_path):
    for mode in ['1', '2', '3', '4', '5', '6', '7', '8']:
        modify_lambda_captures(filename, original_command, log_file_path, mode)


def modify_lambda_captures(filename, original_command, log_file_path, lambda_mode='1'):
    fuzz_mode = "lambda_captures"
    index = clang.cindex.Index.create()
    tu = index.parse(filename)
    
    with open(filename, 'r') as file:
        content = file.read()
    processed_offsets = set()
    
    lambdas = []
    for node in tu.cursor.walk_preorder():
        if node.kind == clang.cindex.CursorKind.LAMBDA_EXPR:
            lambdas.append(node)
    
    if not lambdas:
        logging.info("No lambda expressions found.")
        return None
    
    lambda_node = random.choice(lambdas)
    extent = lambda_node.extent
    start = extent.start.offset
    end = extent.end.offset
    
    original_line = get_line_at_offset(content, start)
    logging.info(f"Original lambda: {original_line}")
    
    lambda_code = content[start:end]
    
    capture_start = lambda_code.find('[')
    capture_end = lambda_code.find(']')
    modified_content = ""
    modified_line = ""
    if capture_start != -1 and capture_end != -1:
        if lambda_mode == '1':
            new_capture = '[]'
        elif lambda_mode == '2':
            new_capture = '[=]'
        elif lambda_mode == '3':
            new_capture = '[&]'
        elif lambda_mode == '4':
            original_capture = lambda_code[capture_start + 1:capture_end]
            new_capture = f"[{', '.join(part.strip() for part in original_capture.split(',')[1:])}]"
        elif lambda_mode == '5':
            original_capture = lambda_code[capture_start + 1:capture_end]
            new_capture = f"[&, {original_capture}]"
        elif lambda_mode == '6':
            original_capture = lambda_code[capture_start + 1:capture_end]
            new_capture = f"[=, {original_capture}]"
        elif lambda_mode == '7':
            original_capture = lambda_code[capture_start + 1:capture_end]
            new_capture = f"[unknown]"
        elif lambda_mode == '8':
            original_capture = lambda_code[capture_start + 1:capture_end]
            capture_items = original_capture.split(',')
            for idx, item in enumerate(capture_items):
                if '&' in item:
                    capture_items[idx] = item.replace('&', '').strip()
                else:
                    capture_items[idx] = '&' + item.strip()

            new_capture = f"[{', '.join(capture_items)}]"
            
        modified_lambda = lambda_code[:capture_start] + new_capture + lambda_code[capture_end+1:]
        modified_content = content[:start] + modified_lambda + content[end:]
        modified_line = get_line_at_offset(modified_content, start)
    else:
        logging.info("Lambda capture list not found.")
        
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.cpp') as temp_file:
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
                        clang.cindex.CursorKind.LAMBDA_EXPR, "SUCCESS", result.stdout.decode().strip(), log_file_path)
        except subprocess.CalledProcessError as e:
            error_message = e.stderr.decode()
            log_to_json(fuzz_mode, original_line,
                        modified_line, clang.cindex.CursorKind.LAMBDA_EXPR, "ERROR", error_message, log_file_path)


    
    return None, None
