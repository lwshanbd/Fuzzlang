import os
import tiktoken

def count_tokens_in_file(file_path, encoding):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        tokens = encoding.encode(content)
        return len(tokens)
    except UnicodeDecodeError:
        # Try reading with a fallback encoding
        try:
            with open(file_path, 'r', encoding='latin-1') as file:
                content = file.read()
            tokens = encoding.encode(content)
            return len(tokens)
        except Exception as e:
            print(f"Skipping {file_path}: {e}")
            return 0
    except Exception as e:
        print(f"Skipping {file_path}: {e}")
        return 0


def count_tokens_in_folder(folder_path, model_name="gpt-4"):
    encoding = tiktoken.encoding_for_model(model_name)
    total_tokens = 0
    
    for root, _, files in os.walk(folder_path):
        for file_name in files:
            if file_name.endswith(('.c', '.cpp')):
                file_path = os.path.join(root, file_name)
                total_tokens += count_tokens_in_file(file_path, encoding)
    
    return total_tokens

if __name__ == "__main__":
    folder_path = "/shared/data1/Users/l1065028/llvm-project/clang/test"
    model_name = "gpt-4o"  # Change to "gpt-4o-mini" if needed
    
    if not os.path.isdir(folder_path):
        print("Invalid folder path")
    else:
        total_tokens = count_tokens_in_folder(folder_path, model_name)
        print(f"Total tokens in folder and subfolders: {total_tokens}")