import json
import re
import glob



errs = []

def escape_special_chars(text):
    return re.sub(r'([.^$+?{}[\]\\()])', r'\\\1', text)

def escape_special_chars_diff(text):
    return re.sub(r'([.*^+?{}[\]\\()])', r'\\\1', text)

def escape_special_chars1(text):
    return re.sub(r'([.^$*+|?{}[\]\\()])', r'\\\1', text)

def escape_special_chars_select(text):
    return re.sub(r'([.^$*+?{}[\]\\()])', r'\\\1', text)

def process_plural_segment(segment):
    plural_pattern = re.compile(r'%plural\{([^}]*)\}\d')
    match = plural_pattern.match(segment)
    if not match:
        return escape_special_chars(segment)
    
    content = match.group(1)
    forms = [part.split(':', 1)[1] for part in content.split('|')]
    formatted_content = '|'.join(forms)
    return f'({escape_special_chars(formatted_content)})'

def remove_comments(input_string):
    return re.sub(r'//.*?\n', '\n', input_string)

def find_matching_brace(s, start):
    count = 1
    for i in range(start + 1, len(s)):
        if s[i] == '{':
            count += 1
        elif s[i] == '}':
            count -= 1
        if count == 0:
            return i
    return -1

def process_diff(input_string, start):
    content_start = input_string.index('{', start) + 1
    content_end = find_matching_brace(input_string, content_start - 1)
    if content_end == -1:
        raise ValueError("Unmatched brace in select")
    
    content = input_string[content_start:content_end]
    processed_content = process_diff_content(content)
    
    number_end = content_end + 3
    while number_end < len(input_string) and input_string[number_end].isdigit():
        number_end += 1
    processed_content = processed_content.replace('$', '.*')
    return f'({processed_content})', number_end

def process_diff_content(content):
    parts = re.split(r'(%select\{[^}]*\}\d*)', content)
    processed_parts = []
    for part in parts:
        if part.startswith('%select'):
            diff_pattern = re.compile(r'%select\{([^}]*)\}\d*')
            match = diff_pattern.match(part)
            if match:
                diff_content = match.group(1)
                processed_parts.append(f'({escape_special_chars_select(diff_content).replace("$", ".*")})')
        else:
            processed_parts.append(escape_special_chars_diff(part))
    return ''.join(processed_parts)

def process_select(input_string, start):
    content_start = input_string.index('{', start) + 1
    content_end = find_matching_brace(input_string, content_start - 1)
    if content_end == -1:
        raise ValueError("Unmatched brace in select")
    
    content = input_string[content_start:content_end]
    processed_content = process_select_content(content)
    
    number_end = content_end + 1
    while number_end < len(input_string) and input_string[number_end].isdigit():
        number_end += 1
    
    return f'({processed_content})', number_end

def process_select_content(content):
    parts = re.split(r'(%diff\{[^}]*\}\d,\d*)', content)
    processed_parts = []
    for part in parts:
        if part.startswith('%diff'):
            diff_pattern = re.compile(r'%diff\{([^}]*)\}\d,\d*')
            match = diff_pattern.match(part)
            if match:
                diff_content = match.group(1)
                processed_parts.append(f'({escape_special_chars_diff(diff_content).replace("$", ".*")})')
        else:
            processed_parts.append(escape_special_chars_select(part))
    return ''.join(processed_parts)

def process_string(input_string):
    input_string = remove_comments(input_string)
    result = []
    index = 0
    
    while index < len(input_string):
        match_found = False
        
        if input_string.startswith('%select', index):
            processed_select, new_index = process_select(input_string, index)
            result.append(processed_select)
            index = new_index
            match_found = True
            
        if input_string.startswith('%diff', index):
            processed_select, new_index = process_diff(input_string, index)
            result.append(processed_select)
            index = new_index
            match_found = True
        
        if not match_found:
            for pattern, output in [
                (re.compile(r'%s\d+'), '.*'),
                (re.compile(r'%ordinal\d+'), '.*'),
                (re.compile(r'%q\d+'), '.*'),
                (re.compile(r'%sub\{([^}]*)\}(?:\d,)*\d'), '.*'),
                (re.compile(r'%plural\{([^}]*)\}\d'), lambda m: process_plural_segment(m.group(0))),
                (re.compile(r'%\d'), '.*'),
            ]:
                match = pattern.match(input_string, index)
                if match:
                    if isinstance(output, str):
                        result.append(output)
                    else:
                        result.append(output(match))
                    index = match.end()
                    match_found = True
                    break
        
        if not match_found:
            result.append(escape_special_chars1(input_string[index]))
            index += 1
    
    res = ''.join(result).replace('"', '').replace('\n', '')
    return res


def extract_errors_from_td(file_path):
    errors = {}
    with open(file_path, 'r') as file:
        content = file.read()
        pattern = r'def\s+(err_\w+)\s*:\s*Error<\s*(.+?)(?=>)'
        pattern = r'def\s+(err_\w+)\s*:\s*Error<(.*?)>(,|;)'

        matches = re.finditer(pattern, content, re.DOTALL)
        for match in matches:
            error_name = match.group(1)
            error_message = match.group(2)
            error_message = re.sub(r'(?m)^\s+', '', error_message)
            error_message = remove_comments(error_message)
            error_message = re.sub(r'(?<!\\)"', '', error_message)
            error_message = re.sub(r'\\n|\n|\r|\t', '', error_message)
            error_message = re.sub(r'\s+', ' ', error_message)
            error_message = error_message.strip()
            error_message = process_string(error_message)
            errors[error_name] = error_message
    return errors

def match_error_messages(errors, messages):
    matched = {}
    notfound = []
    matched['not_found'] = 0
    for message in messages:
        for error_name, error_pattern in errors.items():
            if error_pattern == ".*":
                continue
            if error_pattern == "err_diagnose_if_succeeded":
                continue
            try:
                if re.match(error_pattern, message):
                            if error_name in matched:
                                matched[error_name] += 1
                            else:
                                matched[error_name] = 1
                            # print(f"pattern: {pattern}")
                            # print(f"message: {message}")
                            break
            except:
                # print(f"falied! pattern is :{pattern}")
                print(f"original: {error_pattern}")
                print(f"error_name: {error_name}")
                print(process_string(error_pattern))
                return
        else:
            notfound.append(message)
            matched['not_found'] += 1
    return matched, notfound


def remove_ansi_escape_sequences(text):
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

def extract_errors(text):
    error_pattern = re.compile(r':\s+error:\s+(.*?)(?=\n)', re.DOTALL)
    errors = error_pattern.findall(text)
    
    return errors
    
    
def main():
    all_errors = {}
    file_name = "../log_llvm_removept2.json"
    with open(file_name, 'r') as file:
        for line in file:
            data = json.loads(line)
            errs.append(data)
            
    for td_file in glob.glob('../tdfile/*.td'):
        all_errors.update(extract_errors_from_td(td_file))
    errors = []
    for i in errs:
        str_tmp = i['message']
        str_tmp = remove_ansi_escape_sequences(str_tmp)
        errors.extend(extract_errors(str_tmp))
    results, notfound = match_error_messages(all_errors, errors[:400])
    print(len(results))
    print(results)

if __name__ == "__main__":
    main()