#!/usr/bin/env bash

PYTHONPATH=. python3 fedfaceid/mnist/train_mnist.py \
  --id sanity_check \
  --skip_stopping \
  --distributed \
  --num_user 1 \
  --user_fraction 1.0 \
  --num_global_epochs 400 \
  --num_local_epochs 1 \
  --num_local_batch 100 \
  --learning_rate 0.15 \
  --learning_rate_decay 0.99
