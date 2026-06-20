# Fuzzlang-modified LLVM: patch

One small modification to stock LLVM/Clang.

## Patch

| File | What it does |
|---|---|
| `0001-clang-emit-diag-id-on-stderr.patch` | Modifies `TextDiagnosticPrinter::HandleDiagnostic` to emit `DiagID: <N>` on stderr after each rendered diagnostic (both the main path and the invalid-location / command-line path). |

## Why no second patch?

The original Fuzzlang paper (Section 3.1.2) mentions adding a `find-diagnostic-name` subcommand to `diagtool`. This turns out to be unnecessary in stock **LLVM ≥ 17**: the existing `find-diagnostic-id` already falls back to reverse-lookup when given an integer argument. See `clang/tools/diagtool/FindDiagnosticID.cpp` lines 22-28 + 62-67 in LLVM 22.1.8:

```cpp
// Name to id failed, so try id to name.
auto Name = getNameFromID(DiagnosticName);
if (!Name.empty()) {
  OS << Name << '\n';
  return 0;
}
```

So:
```
$ diagtool find-diagnostic-id err_expected_semi
<number>
$ diagtool find-diagnostic-id <number>
err_expected_semi
```

One binary, both directions. The FuzzLang verifier (`src/foundation/verifier/fuzzlang.py`) calls `diagtool find-diagnostic-id <integer>` to recover the diag name from the ID printed by Patch 1.

## Applying

```bash
cd llvm-project/
git apply --check scripts/patches/0001-clang-emit-diag-id-on-stderr.patch
git apply scripts/patches/0001-clang-emit-diag-id-on-stderr.patch
```

If `git apply --check` fails, the surrounding lines in `TextDiagnosticPrinter.cpp` have drifted from LLVM 22.1.8. Manual re-derivation takes two minutes: in `HandleDiagnostic(...)`, add
```cpp
OS << "DiagID: " << Info.getID() << "\n";
```
immediately before each call to `OS.flush()` (once in the invalid-location early-return branch, once at the end of the function).

## Verifying after build

```bash
$ echo 'int main() { int x = 1 }' > /tmp/t.c
$ clang -c /tmp/t.c 2>&1 | grep -E "^DiagID:"
DiagID: <number>

$ diagtool find-diagnostic-id <number>
err_expected_semi   # or the actual name for that diagnostic
```
