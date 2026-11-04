# Test fixtures

This directory contains small, synthetic inputs for regression tests:

- `pricing/flash-cny.json`: values for the frozen CNY accounting protocol.
- `pricing/flash-table.html`: a merged-cell HTML table for the pricing parser.

These files are test data, not current tariffs, account observations or experiment evidence. Provider endpoint and Docker error responses are constructed directly in the relevant tests.

Historical self-check reports, captured API responses and campaign recovery records live outside Git. Tests that validate those original records require the external inputs described in [storage](../../docs/storage.md). New test output belongs in a temporary directory or `.scratch/`.
