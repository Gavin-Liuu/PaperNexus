# ONNX Embedding Benchmark

Measured on 2026-09-18 with the 250-paper `metalens-lazy-atlas.json` corpus,
`BAAI/bge-small-en-v1.5`, FastEmbed, and a temporary vector cache.

The laptop was connected to AC power (`BatteryStatus=2`, Windows power plan:
High performance). ONNX Runtime reported `AzureExecutionProvider` and
`CPUExecutionProvider`; the RTX 4050 was not used.

| Batch | First encoding | Per paper | Cached read |
|---:|---:|---:|---:|
| 1 | 0.046 s | 46.1 ms | 0.001 s |
| 10 | 0.721 s | 72.1 ms | 0.004 s |
| 50 | 5.078 s | 101.6 ms | 0.018 s |
| 100 | 9.645 s | 96.4 ms | 0.031 s |
| 250 | 23.296 s | 93.2 ms | 0.084 s |

The earlier battery-mode run on the same corpus measured 31.707 s for 250
papers. AC power reduced that full-batch time by about 26.5%.

For the product path, encode titles and topics for the first-stage filter, then
encode abstracts only for the top 20--30 candidates. This keeps interactive
branch growth close to a few seconds and makes repeated views cache-bound.
