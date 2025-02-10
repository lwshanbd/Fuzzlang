import os
import re
import chardet
import json

def extract_expected_errors(directory):
    """
    Extract all expected-error messages from C/C++ files
    
    Args:
        directory (str): Directory path to search
    
    Returns:
        list: List containing all matching expected-error messages
    """
    error_messages = []
    extensions = ('.c', '.cpp', '.cc', '.cxx')
    
    # Updated pattern to match any content within expected-error{{}}
    pattern = r"(expected-error(?:@(?:\+\d+|[\w.]+:\*?))?)\s*{{([^}]+)}}"
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(extensions):
                file_path = os.path.join(root, file)
                try:
                    # First detect the file encoding
                    with open(file_path, 'rb') as f:
                        raw_data = f.read()
                        detected = chardet.detect(raw_data)
                        encoding = detected['encoding'] or 'utf-8'
                    
                    # Then read the file with detected encoding
                    try:
                        content = raw_data.decode(encoding)
                    except UnicodeDecodeError:
                        # Fallback encodings if the detected one fails
                        for fallback_encoding in ['latin1', 'iso-8859-1', 'cp1252']:
                            try:
                                content = raw_data.decode(fallback_encoding)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            print(f"Failed to decode file {file_path} with any encoding")
                            continue
                    
                    # Find all matches
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        error_messages.append({
                            'file': file_path,
                            'error_full': match.group(0),  # Full error message including expected-error{{}}
                            'error_content': match.group(2).strip(),  # Just the content inside {{}}
                            'line_number': content.count('\n', 0, match.start()) + 1
                        })
                        
                except Exception as e:
                    print(f"Error processing file {file_path}: {str(e)}")
    
    return error_messages

def print_results(errors):
    """
    Print extracted results
    """
    if not errors:
        print("No matching expected-error messages found")
        return
        
    print(f"Found {len(errors)} matches:")
    print("-" * 80)
    for error in errors:
        print(f"File: {error['file']}")
        print(f"Line: {error['line_number']}")
        print(f"Full Error: {error['error_full']}")
        print(f"Error Content: {error['error_content']}")
        print("-" * 80)


directory = "../../tmp/llvm-project/clang/test"  # Replace with actual directory path
errors = extract_expected_errors(directory)
with open("error-1.jsonl",'w') as f:
    for i in errors:
        json_line = json.dumps(i)
        f.write(json_line + '\n')
