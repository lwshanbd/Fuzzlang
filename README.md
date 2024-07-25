# Fuzzlang

## Fuzz mode of Fuzzlang

1. Modify the compiliation args

```shell
export FUZZ_MODE = [fuzz_mode]
```
fuzz_mode:
- reorder
- remove
- replace
- insert

2. Modify source code
```shell
export FUZZ_MODE=[fuzz_mode]
```
fuzz_mode:
- remove_parentheses
- replace_colon_with_semicolon
- add_asterisk_to_variables
