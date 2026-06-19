import utils

error_file_path = "/shared/data1/Users/l1065028/Fuzzlang/src/llvm_test_agent/success_files/"
error_files = utils.get_all_files(error_file_path)

open("error_list.txt", "w").write("\n".join(error_files))

x = open("error_list.txt", "r").readlines()

print(len(x))
print(x[0][:-1])
