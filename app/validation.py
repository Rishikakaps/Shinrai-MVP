"""Bounded PDF structure validation invoked before accepting an upload."""

import io
import resource
import sys

from pypdf import PdfReader


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    content = sys.stdin.buffer.read(12 * 1024 * 1024 + 1)
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 12:
        raise ValueError("Encrypted, empty, or excessive PDF pages")


if __name__ == "__main__":
    main()
