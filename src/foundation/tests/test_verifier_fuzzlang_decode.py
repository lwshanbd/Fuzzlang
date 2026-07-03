"""FuzzlangClangVerifier must tolerate non-UTF-8 bytes on clang's stderr.

Some frontend configs (certain targets / inputs) make clang emit non-UTF-8
bytes in a diagnostic. Strict decoding crashed the whole mining sweep; the
verifier must decode robustly and still parse the DiagID.
"""
from __future__ import annotations

import os

from foundation.verifier.base import PLACEHOLDER
from foundation.verifier.fuzzlang import FuzzlangClangVerifier


def test_verify_tolerates_non_utf8_stderr(tmp_path):
    fake = tmp_path / "fakeclang"
    # Emits an error line containing a raw 0xb2 byte, then a DiagID, exits 1.
    fake.write_text(
        '#!/bin/bash\n'
        r'printf "f.c:1:1: error: bad \xb2 byte\nDiagID: 42\n" >&2' + '\n'
        'exit 1\n'
    )
    os.chmod(fake, 0o755)

    v = FuzzlangClangVerifier(str(fake), "/bin/true")
    result = v.verify("int x;", ["__CLANG__", PLACEHOLDER], logical_path="f.c")

    assert not result.ok
    assert result.diag is not None
    assert result.diag.diag_id == 42        # parsed despite the bad byte
    assert "DiagID:" in result.raw_stderr
