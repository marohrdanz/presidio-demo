# Synthetic Demo Data

The script uses only the Python standard library.

Running python generate\_synthetic\_phi.py produces seven test CSVs plus a manifest.json that records
the ground truth for each one. The manifest lists which columns hold which entity types, and for the
free-text columns it gives the exact character positions of every piece of embedded PHI. That lets you
calculate recall and precision automatically instead of eyeballing results.

The seven files each test a different weakness:

1. `labeled.csv` is the easy baseline, with descriptive headers.
2. `obfuscated.csv` has the same kinds of PHI under generic or misleading headers like code and ref,
        with MRNs as plain integers and SSNs and phone numbers as bare digits.
3. `formats.csv` mixes five date formats and five phone formats within the same columns, along
     with "Last, First" names, ZIP+4 codes, and ages over 89.
4. `freetext.csv` contains clinical notes, about half of which have embedded names, relatives, addresses,
       employers, URLs, and IP addresses.
5. `sparse.csv` has PHI in only three comments out of hundreds of rows, to catch scans that only sample rows.
6. `negative_control.csv` is de-identified data where any detection is a false positive. It deliberately
       includes eponymous diagnoses like Parkinson's and Crohn's, which NER models often tag as person names.
7. `quasi_identifiers.csv` contains no direct identifiers, but a few rows are unique on their combination
      of columns. This one tests your k-anonymity check rather than Presidio.


Reserved ranges are used wherever they exist, so values can't belong to real people: 555-01xx phone numbers,
example.com domains, documentation IP ranges, and SSNs in the never-issued 900–999 range. One thing to watch
is that some detectors reject 9xx SSNs as invalid. If Presidio misses them, rerun with --realistic-ssn to
see whether it's a format issue or a validity rule. Set --mrn-format to match your institution's real MRN pattern.
In the pattern, # stands for a digit, A for a letter, and any other character is kept as written.
A custom MRN recognizer is one of the most valuable additions you can make to Presidio. The manifest also marks
provider names as PERSON_PROVIDER with phi: false. They aren't Safe Harbor identifiers for the patient, but
Presidio will flag them, so you'll want to decide on a policy for them.

