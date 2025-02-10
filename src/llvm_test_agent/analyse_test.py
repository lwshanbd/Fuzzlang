import multiprocessing
import json
import re
import glob
import os


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
                processed_parts.append(
                    f'({escape_special_chars_select(diff_content).replace("$", ".*")})')
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
    def process_nested(nested_content):
        nested_parts = re.split(r'(%select\{[^}]*\}\d*|%diff\{[^}]*\}\d,\d*)', nested_content)
        processed_nested_parts = []
        for nested_part in nested_parts:
            if nested_part.startswith('%select'):
                select_pattern = re.compile(r'%select\{([^}]*)\}\d*')
                match = select_pattern.match(nested_part)
                if match:
                    select_content = match.group(1)
                    processed_nested_parts.append(f'({process_nested(select_content)})')
            elif nested_part.startswith('%diff'):
                diff_pattern = re.compile(r'%diff\{([^}]*)\}\d,\d*')
                match = diff_pattern.match(nested_part)
                if match:
                    diff_content = match.group(1)
                    processed_nested_parts.append(
                        f'({escape_special_chars_diff(diff_content).replace("$", ".*")})')
            else:
                part = escape_special_chars_select(nested_part)
                part = re.sub(r'%\d', '.*', part)
                processed_nested_parts.append(part)
        return ''.join(processed_nested_parts)

    return process_nested(content)


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
                (re.compile(r'%plural\{([^}]*)\}\d'),
                 lambda m: process_plural_segment(m.group(0))),
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
        pattern = r'def\s+(\w+)\s*:\s*Error\s*<(.*?)>(,|;)'

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
    with open(file_path, 'r') as file:
        content = file.read()
        pattern = r'def\s+(\w+)\s*:\s*ExtWarn\s*<(.*?)>(,|;)'
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


def process_message(message, errors):
    msg_info = message['error_content']
    process_name = multiprocessing.current_process().name
    error_names = []
    for error_name, error_pattern in errors.items():
        if error_pattern == ".*":
            continue
        if error_pattern == "err_diagnose_if_succeeded":
            continue
        try:
            if re.match(error_pattern, msg_info):
                error_names.append(error_name)
                #message['error_name'] = error_name
                #return (message, error_name)
        except:
            continue
    return (message, error_names)


def match_error_messages_parallel(errors, error_messages):
    matched = {}
    notfound = []
    matched['not_found'] = 0

    with multiprocessing.Pool(processes=56) as pool:
        results = pool.starmap(
            process_message, [(message, errors) for message in error_messages])

    for message, result in results:
        if len(result) > 0:
            for error_name in result:
                if error_name in matched:
                    matched[error_name] += 1
                else:
                    matched[error_name] = 1
            # if result in matched:
            #     matched[result] += 1
            # else:
            #     matched[result] = 1
            message['error_name'] = result
        else:
            notfound.append(message['error_content'])
            matched['not_found'] += 1
            message['error_name'] = None
    return matched, notfound, [result[0] for result in results]


def match_error_messages(errors, error_messages):
    matched = {}
    notfound = []
    matched['not_found'] = 0
    for message in error_messages:
        msg = message['error_content']
        for error_name, error_pattern in errors.items():
            if error_pattern == ".*":
                continue
            if error_pattern == "err_diagnose_if_succeeded":
                continue
            try:
                if re.match(error_pattern, msg):
                    message['error_name'] = error_name
                    if error_name in matched:
                        matched[error_name] += 1
                    else:
                        matched[error_name] = 1
                    break
            except:
                # print(f"falied! pattern is :{pattern}")
                print(f"original: {error_pattern}")
                print(f"error_name: {error_name}")
                print(process_string(error_pattern))
                return
        else:
            notfound.append(msg)
            matched['not_found'] += 1
    return matched, notfound


def remove_ansi_escape_sequences(text):
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)


def extract_errors(text):
    error_pattern = re.compile(r':\s+error:\s+(.*?)(?=\n)', re.DOTALL)
    errors = error_pattern.findall(text)

    return errors

def process_json(file_name):
    errs = []
    with open(file_name, 'r') as file:
        for line in file:
            data = json.loads(line)
            errs.append(data)
    return errs

def main():
    all_errors = {}
    for td_file in glob.glob('/shared/data1/Users/l1065028/llvm-project/clang/include/clang/Basic/*.td'):
        all_errors.update(extract_errors_from_td(td_file))
    errors = []

        
    with open('error-1.jsonl', 'r') as f:
        err_messages = [json.loads(line) for line in f]    


    results, notfound, err_messages = match_error_messages_parallel(all_errors, err_messages)
    print(len(err_messages))
    
    with open("error_types-1.jsonl",'w') as f:
        for i in err_messages:
            json_line = json.dumps(i)
            f.write(json_line + '\n')
    
    with open('notfound-1.list', 'w') as file:
        for element in notfound:
            file.write(f"{element}\n")
    print(len(results))

    filename = 'llvm_test_errortype-1.json'

    with open(filename, 'w') as json_file:
        json.dump(results, json_file, indent=4)


if __name__ == "__main__":
    main()
