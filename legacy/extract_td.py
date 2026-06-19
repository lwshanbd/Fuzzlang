import os
import re

def extract_error_names_from_folder(folder_path):
    # Regular expression to match error names
    pattern = r"def\s+([a-zA-Z0-9_]+)\s*:"

    error_names = []

    # Iterate through all .td files in the folder
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".td"):
                file_path = os.path.join(root, file)
                print(f"Processing file: {file_path}")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Extract all matching error names
                        matches = re.findall(pattern, content)
                        error_names.extend(matches)
                except Exception as e:
                    print(f"Failed to read {file_path}: {e}")

    return error_names


folder_path = "tdfile"


# Extract error names
error_names = extract_error_names_from_folder(folder_path)
res = []
for i in error_names:
    if "err_" in i:
        res.append(i)
print(len(res))

with open("omp_errors.txt", "r") as f:
    omp_errors = f.readlines()
    omp_errors = [i.strip() for i in omp_errors]
print(len(omp_errors))
ans = []
for err in omp_errors:
    if err not in res:
        ans.append(err)
        print(err)
print(len(ans))
