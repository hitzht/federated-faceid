#!/usr/bin/env bash

PYTHONPATH=. python3 fedfaceid/mnist/train_mnist.py \
    --id Baseline \
    --num_global_batch 100 \
    --num_global_epochs 400 \
    --learning_rate 0.15 \
    --learning_rate_decay 0.99 \
    --skip_stopping

