#!/bin/bash
#
# Pre-Task-4-3 stopgap corpus downloader for bpetite.
#
# PRD task 4-3 specifies this as `scripts/download_corpus.py` (pure Python
# via urllib.request). Until that task lands, this bash shim fetches the
# same corpus to the same PRD-authoritative destination path so the
# downstream training/evaluation pipelines can find it.
#
# Destination must stay at `data/tinyshakespeare.txt` per the PRD task
# list; changing the path desynchronizes the `forbid-generated-artifacts`
# hook, .gitignore, and task 2-6 acceptance criteria.
#
set -e

mkdir -p data
curl -L -o data/tinyshakespeare.txt \
  https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt
echo "Done. Training data saved to data/tinyshakespeare.txt"
