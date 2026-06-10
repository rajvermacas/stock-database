import csv
import sys

input_csv = sys.argv[1]
output_csv = sys.argv[2]

seen = set()

with open(input_csv, "r", newline="", encoding="utf-8") as infile, \
     open(output_csv, "w", newline="", encoding="utf-8") as outfile:

    reader = csv.reader(infile)
    writer = csv.writer(outfile)

    # Preserve header
    header = next(reader)
    writer.writerow(header)

    # Remove duplicate rows while preserving order
    for row in reader:
        row_tuple = tuple(row)

        if row_tuple not in seen:
            seen.add(row_tuple)
            writer.writerow(row)

print(f"Duplicates removed. Output written to {output_csv}")