# Fuzzlang-modified LLVM: patches

Two small modifications to stock LLVM/Clang. Both are needed for DVCR's full
observation channel (the `{diag_id, diag_name, ...}` variant). The paper
describes them in Section 3.1.

## Patches

| File | What it does |
|---|---|
| `0001-clang-emit-diag-id-on-stderr.patch` | Modifies `TextDiagnosticPrinter` to emit `DiagID: <N>` on stderr immediately after each rendered diagnostic. Internal diagnostic ID only; no text-based disambiguation required. |
| `0002-diagtool-find-diagnostic-name.patch` | Adds a new `find-diagnostic-name <ID>` subcommand to `diagtool`. Reverses the existing `find-diagnostic-id <NAME>` lookup. |

## Targeted LLVM version

Developed against **LLVM 19.1.7** (matches `llvm/release-19.1.7` available on ALCF Polaris).
Patches are expected to apply cleanly to 17/18/19 with minor fuzz. If `patch`
reports rejected hunks, re-derive manually per the anchor points below.

## Manual derivation if hunks reject

### Patch 1 (emit DiagID on stderr)

Find `clang/lib/Frontend/TextDiagnosticPrinter.cpp`. Locate `TextDiagnosticPrinter::HandleDiagnostic(...)`. Immediately after the call to `TextDiag->emitDiagnostic(...)` (or its equivalent) — i.e. after the diagnostic body has been rendered — emit:

```cpp
// Fuzzlang: emit the internal diagnostic ID for programmatic classification.
if (OS) {
  *OS << "DiagID: " << Info.getID() << "\n";
  OS->flush();
}
```

The `OS` pointer is the class's `raw_ostream`. `Info.getID()` returns the
internal `unsigned` diagnostic ID (the same vocabulary that `diagtool
find-diagnostic-id <name>` produces).

### Patch 2 (diagtool find-diagnostic-name)

Under `clang/tools/diagtool/`:
1. Add a new file `FindDiagnosticName.cpp` implementing the subcommand (source included in patch).
2. Register it in `DiagTool.cpp`'s handler table (the registry pattern used by `FindDiagnosticID`).
3. Add the new file to `CMakeLists.txt`.

The implementation is the symmetric lookup: iterate the `DiagnosticIDs` table, find the entry whose ID matches, print the name.

## Applying

```bash
cd llvm-project/
git apply --check ../fuzzlang-clang/scripts/patches/0001-clang-emit-diag-id-on-stderr.patch
git apply --check ../fuzzlang-clang/scripts/patches/0002-diagtool-find-diagnostic-name.patch
git apply ../fuzzlang-clang/scripts/patches/0001-clang-emit-diag-id-on-stderr.patch
git apply ../fuzzlang-clang/scripts/patches/0002-diagtool-find-diagnostic-name.patch
```

If `git apply --check` fails, fall back to manual derivation per the anchors above, or use `patch -p1 --fuzz=3` and fix rejected hunks by hand.

## Verifying after build

```bash
# Patch 1: compile a source with a known error and look for the DiagID line.
$ echo 'int main() { int x = 1 }' > /tmp/t.c
$ clang -c /tmp/t.c 2>&1 | grep -E "^DiagID:"
DiagID: <number>

# Patch 2: look up the diagnostic name from the ID emitted above.
$ diagtool find-diagnostic-name <number>
err_expected_semi   # or the actual name for that diagnostic
```
