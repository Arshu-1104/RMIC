"""Download the datasets of the real-data evaluation (experiment/eval_real_data/).

    python scripts/fetch_real_eval_data.py

Downloads from pinned revisions into the git-ignored data/real_eval/ and checks the SHA-256 of
every file; a file that does not match is not written. The repository never stores these files.

- Lakera "gandalf_ignore_instructions" (huggingface.co/datasets/Lakera/gandalf_ignore_instructions),
  MIT licence: 1,000 prompt-injection attempts by players of the Gandalf game.
- Banking77 (PolyAI; github.com/PolyAI-LDN/task-specific-datasets, the files the Hugging Face
  PolyAI/banking77 loader downloads), CC BY 4.0: 13,083 online-banking queries, 77 intents.
  Casanueva et al., "Efficient Intent Detection with Dual Sentence Encoders", NLP4ConvAI 2020.

Reading the Gandalf parquet files needs pyarrow (pip install pyarrow); this script does not.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / "data" / "real_eval"

GANDALF_REVISION = "04737b65e90a6794ec227012e4a255a7def6344b"
BANKING77_COMMIT = "9d081458ff52e53cf7e848f414e6e9344e4e6696"
_G = f"https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions/resolve/{GANDALF_REVISION}/data"
_B = f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{BANKING77_COMMIT}/banking_data"

# local path (relative to DEST) -> (url, sha256)
FILES: dict[str, tuple[str, str]] = {
    "gandalf/train-00000-of-00001-ded53be747ff55cd.parquet": (
        f"{_G}/train-00000-of-00001-ded53be747ff55cd.parquet",
        "5b6acf3e5a5998d21f8e1222bb45bbdec25a14408747b1cd63bebef4a75fa439",
    ),
    "gandalf/validation-00000-of-00001-94481a2a09ff2fff.parquet": (
        f"{_G}/validation-00000-of-00001-94481a2a09ff2fff.parquet",
        "f51ab3e3407a368845b0f57932cc745c09280429416d7507bd178a16326a79f6",
    ),
    "gandalf/test-00000-of-00001-bc92128b9288a6d1.parquet": (
        f"{_G}/test-00000-of-00001-bc92128b9288a6d1.parquet",
        "56b646d133335ebc535266bd55dbe1b5bee7caa4b95bf49d040684b9b5dd9972",
    ),
    "banking77/train.csv": (f"{_B}/train.csv", "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b"),
    "banking77/test.csv": (f"{_B}/test.csv", "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"),
    "banking77/categories.json": (
        f"{_B}/categories.json",
        "53261da888122daf2d120d925458631d9619e15d82e56052e7a42e535ce32b63",
    ),
}

LICENCES = (
    "Lakera gandalf_ignore_instructions: MIT licence (Lakera AI).",
    "Banking77: CC BY 4.0 (PolyAI; Casanueva et al., NLP4ConvAI 2020). Attribution required.",
)


class ChecksumError(RuntimeError):
    pass


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(
    dest: Path = DEST,
    files: dict[str, tuple[str, str]] = FILES,
    download: Callable[[str], bytes] = _download,
) -> list[Path]:
    """Download every file whose local copy is missing or wrong; verify each against its SHA-256.

    Raises ChecksumError (and leaves no file behind) when a download does not match."""
    paths = []
    for rel, (url, digest) in files.items():
        path = dest / rel
        if not (path.exists() and sha256(path.read_bytes()) == digest):
            body = download(url)
            got = sha256(body)
            if got != digest:
                raise ChecksumError(f"{rel}: SHA-256 {got} does not match the pinned {digest}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        paths.append(path)
    return paths


def main() -> int:
    try:
        paths = fetch()
    except ChecksumError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(f"ok  {path.relative_to(REPO).as_posix()}")
    print("\n".join(LICENCES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
