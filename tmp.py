import json
import re

def extract_error_and_diag_ids(jsonl_file):
    diag_id_pattern = r"DiagID:\s*(\d+)"  # 正则表达式匹配 DiagID
    diagids = []
    with open(jsonl_file, 'r', encoding='utf-8') as file:
        for line in file:
            try:
                # 解析 JSONL 行
                json_obj = json.loads(line.strip())
                
                # 提取 error 信息
                error_info = json_obj.get("message", "")
                
                # 查找所有 DiagID
                diag_id_matches = re.findall(diag_id_pattern, error_info)
                diagids.extend(diag_id_matches)  # 添加所有匹配的 DiagID
            except json.JSONDecodeError as e:
                print(f"Failed to parse line: {line.strip()} with error: {e}")
    return diagids

# 替换为你的 JSONL 文件路径
jsonl_file_paths = ["total-jsons/agent.jsonl", "total-jsons/remove_single_id.jsonl", "total-jsons/add_asterisk_id.jsonl"]
res = []
for file in jsonl_file_paths:
    res.extend(extract_error_and_diag_ids(file))
    
unique_lst = list(set(res))
print(len(res))       # 输出总匹配数
print(len(unique_lst))  # 输出唯一 DiagID 数量