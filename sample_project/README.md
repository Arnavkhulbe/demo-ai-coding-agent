# Sample Shop (the agent's target project)

This is a tiny, realistic Python package that the **AI Coding Agent** is pointed
at by default. It contains one intentional bug so you can watch the agent find
and fix a real defect.

## Layout

| File | Purpose |
| --- | --- |
| `shop/pricing.py` | Discount and VAT maths. **Contains the bug.** |
| `shop/orders.py` | Builds on `pricing.py` to total up an order. |
| `tests/test_pricing.py` | Unit tests for `pricing.py`. |
| `tests/test_orders.py` | Unit tests for `orders.py`. |

## Run the tests

```bash
cd sample_project
python -m pytest -q
```

You should see failures. The tests describe the *intended* behaviour; the
implementation in `shop/pricing.py` is wrong.

Do not "fix" it by hand if you want to watch the agent do it — that is the whole
demonstration.
