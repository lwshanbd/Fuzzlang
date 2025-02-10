from clang.cindex import Index, CursorKind, TokenKind
import json
import tempfile
import os
import re
#{"file": "../../tmp/llvm-project/clang/test/SemaCXX/default2.cpp", "error_full": "expected-error{{default argument references parameter 'j'}}", "error_content": "default argument references parameter 'j'", "line_number": 67, "error_name": ["err_param_default_argument_references_param"]}
def analyze_pragmas(code, error_pattern, error_line):
    # Create a temporary file with the code
    with tempfile.NamedTemporaryFile(suffix='.c', delete=False, mode='w') as f:
        f.write(code)
        temp_filename = f.name

    try:
        # Initialize clang
        index = Index.create()
        
        # Parse the file
        tu = index.parse(temp_filename, args=['-Xclang', '-fsyntax-only'])
        
        # Split code into lines for later use
        lines = code.split('\n')
        
        # # Find all lines with errors
        # error_lines = []
        # for i, line in enumerate(lines, 1):
        #     if error_pattern in line and line.strip().startswith('#pragma'):
        #         error_lines.append(i)
        
        # Get all tokens
        tokens = list(tu.get_tokens(extent=tu.cursor.extent))
        
        pragmas = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            
            # Start of pragma
            if token.spelling == '#':
                current_line = token.location.line
                if current_line == error_line:
                    # Find scope end
                    scope_end = current_line
                    j = i
                    while j < len(tokens):
                        if tokens[j].spelling == ';':
                            scope_end = tokens[j].location.line
                            break
                        j += 1
                    
                    # Collect all lines in the scope
                    scope_content = []
                    for line_num in range(current_line - 1, scope_end):
                        if line_num < len(lines):  # Check array bounds
                            scope_content.append(lines[line_num].strip())
                    
                    pragmas.append({
                        'scope_content': scope_content,
                        'original_line': lines[current_line - 1].strip(),
                        'line': current_line,
                        'scope_start': current_line,
                        'scope_end': scope_end
                    })
            i += 1
                
        return pragmas

    finally:
        # Clean up temporary file
        os.unlink(temp_filename)
        
def main():
    with open('error-types-1.jsonl', 'r') as f:
        err_messages = [json.loads(line) for line in f]
    for err_msg in err_messages:
        file_path = err_msg['file']
        error_content = err_msg['error_content']
        line_number = err_msg['line_number']
        
        

if __name__ == "__main__":
    main()
