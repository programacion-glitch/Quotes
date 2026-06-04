# Progressive option catalogs

Each JSON lists the valid Progressive options for one field, used by
`preflight.py` to validate a Blue Quote OFFLINE before opening the browser.

In-flight, pages enumerate the REAL on-screen options (live is authoritative);
these catalogs are the offline pre-check only.

## Refreshing a catalog (when Progressive changes its options)

1. Run a quote live with the DIAG dump enabled for the field.
2. Copy the `[Progressive] DIAG combos/options: [...]` line from the log.
3. Replace `options` in the JSON and bump `captured` to today.
4. `python -m pytest tests/progressive/test_catalogs.py -v` must stay green.

**Note:** `generic_aliases` values should be stored **lowercase** in the JSON — the loader lowercases them defensively, but keeping the source consistent avoids surprises.
