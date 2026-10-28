# Table 2.1. Model Performance Summary

| Model    | Evaluation                      | Accuracy / Exact Match   | Precision   | Recall   | F1-Score   | Metric definition                                     |
|:---------|:--------------------------------|:-------------------------|:------------|:---------|:-----------|:------------------------------------------------------|
| Intent   | 5-fold cross-validation (n=457) | 97.37%                   | 97.37%      | 97.37%   | 97.35%     | Intent precision/recall/F1 are macro-averaged         |
| Intent   | Held-out test (n=248)           | 98.79%                   | 98.81%      | 98.79%   | 98.79%     | Intent precision/recall/F1 are macro-averaged         |
| Material | 5-fold cross-validation (n=884) | 91.29%                   | 93.03%      | 95.46%   | 94.23%     | Exact match; micro-averaged label precision/recall/F1 |
| Material | Standard test (n=60)            | 88.33%                   | 90.54%      | 100.00%  | 95.04%     | Exact match; micro-averaged label precision/recall/F1 |
| Material | Blind test (n=73)               | 76.71%                   | 88.16%      | 97.81%   | 92.73%     | Exact match; micro-averaged label precision/recall/F1 |
| Material | Mixed test (n=70)               | 98.57%                   | 100.00%     | 99.70%   | 99.85%     | Exact match; micro-averaged label precision/recall/F1 |

# Table 3.1. Intent Classifier Performance Metrics

| Evaluation                      | Accuracy / Exact Match   | Precision   | Recall   | F1-Score   |
|:--------------------------------|:-------------------------|:------------|:---------|:-----------|
| 5-fold cross-validation (n=457) | 97.37%                   | 97.37%      | 97.37%   | 97.35%     |
| Held-out test (n=248)           | 98.79%                   | 98.81%      | 98.79%   | 98.79%     |

# Table 3.2. Material Classifier Performance Metrics Across Test Sets

| Evaluation                      | Accuracy / Exact Match   | Precision   | Recall   | F1-Score   |
|:--------------------------------|:-------------------------|:------------|:---------|:-----------|
| 5-fold cross-validation (n=884) | 91.29%                   | 93.03%      | 95.46%   | 94.23%     |
| Standard test (n=60)            | 88.33%                   | 90.54%      | 100.00%  | 95.04%     |
| Blind test (n=73)               | 76.71%                   | 88.16%      | 97.81%   | 92.73%     |
| Mixed test (n=70)               | 98.57%                   | 100.00%     | 99.70%   | 99.85%     |

## Metric definitions

- Intent precision, recall, and F1 are macro averages.
- Material exact match requires every predicted label to match the expected label set. Material precision, recall, and F1 are micro averages over material labels.
- Cross-validation retrains a fresh model within each fold in memory; saved model files are not overwritten.
