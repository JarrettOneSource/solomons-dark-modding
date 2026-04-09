#!/usr/bin/env python3
import argparse
import os
import sys

from rapidocr_onnxruntime import RapidOCR


def main() -> int:
    if os.name != "nt":
        print("ocr_image.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Run OCR against an image and print recognized text.")
    parser.add_argument("image_path")
    args = parser.parse_args()

    engine = RapidOCR()
    result, _ = engine(args.image_path)
    if not result:
        print("(no text)")
        return 0

    for item in result:
        points, text, score = item
        print(f"{score}\t{text}\t{points}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
