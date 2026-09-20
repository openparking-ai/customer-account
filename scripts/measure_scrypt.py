#!/usr/bin/env python3
"""Time one scrypt hash across candidate parameters, on THIS machine.

    python scripts/measure_scrypt.py            # the table, and the pick
    python scripts/measure_scrypt.py --budget-ms 250

**THE PARAMETERS THIS MODULE STATES WERE MEASURED, NOT CHOSEN.** Nothing in
this project hashed a human password before this module, so there was no prior
value to copy, and "establish it" without a method is a pick. The method: time
a single ``hashlib.scrypt`` over the candidate cost factors below and take the
LARGEST ``n`` whose one hash stays under the budget. The number is produced by
this command rather than typed, and the value the module states
(``customer_account.passwords.SCRYPT``) is checked against it in the receipt
that ships the round -- with the machine it was measured on named, because this
project has no reference hardware.

``r`` and ``p`` are held at 8 and 1, the values scrypt's own paper and the
OWASP cheat sheet hold them at; the cost factor ``n`` is the axis that moves.
``maxmem`` is stated because CPython's default (32 MiB) refuses ``n`` above
2**14 at ``r=8``; the 128*r*n bytes a hash needs is what is asked for, with
headroom.

The parameters are STORED beside every hash, so raising them later on faster
hardware invalidates no existing row -- see the migration and the contract.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import time

CANDIDATES = (2**12, 2**13, 2**14, 2**15, 2**16, 2**17)
R, P, DKLEN = 8, 1, 64


def one_hash_ms(n: int, r: int = R, p: int = P) -> float:
    password, salt = b"measure-only, never stored", os.urandom(16)
    maxmem = 128 * r * n * 2
    started = time.perf_counter()
    hashlib.scrypt(password, salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=maxmem)
    return (time.perf_counter() - started) * 1000


def main(argv: list[str]) -> int:
    budget = 250.0
    if "--budget-ms" in argv:
        budget = float(argv[argv.index("--budget-ms") + 1])
    print(f"machine: {platform.machine()} {platform.system()} {platform.release()}, "
          f"python {platform.python_version()}")
    print(f"budget: one hash under {budget:.0f} ms; r={R} p={P} dklen={DKLEN}")
    print(f"{'n':>8} {'log2':>5} {'median ms':>10}  (5 runs)")
    pick = None
    for n in CANDIDATES:
        runs = sorted(one_hash_ms(n) for _ in range(5))
        median = runs[2]
        print(f"{n:>8} {n.bit_length() - 1:>5} {median:>10.1f}")
        if median < budget:
            pick = n
    if pick is None:
        print("no candidate met the budget; this machine is slower than every value tried")
        return 1
    print(f"\npick: n=2**{pick.bit_length() - 1} ({pick}), r={R}, p={P}, dklen={DKLEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
