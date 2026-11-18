# Commerce Fraud Investigator Console

A fraud analyst console for a simulated Adobe-style subscription business: it generates customer, payment, login, trial, usage and dispute data, injects real-world fraud patterns, detects them in SQL, and recommends responses that balance fraud loss against customer friction.

> **All data in this project is synthetic.** It is generated with Faker and a fixed random seed. No real people, cards or accounts are involved.

## Quick start

```bash
make setup   # create .venv and install requirements
make all     # generate data, run detection SQL, run tests
make app     # launch the Streamlit console (coming soon)
```

## Status

- [x] Schema, SQL macros, deterministic baseline generator with legit noise
- [x] Card testing: injector with lookalikes, detection SQL, evaluation (recall 1.00, FPR 0 on seed 42)
- [x] Trial abuse: email normalization, identity graph, detection, evaluation (recall 0.99, FPR 0 on seed 42)
- [x] Account takeover: anchor logins, impossible travel, ordered event chain (recall 0.99, FPR 0 on seed 42)
- [x] Friendly fraud and chargeback lifecycle (recall 1.00, FPR 0 on seed 42)
- [ ] Response ladder
- [ ] Streamlit screens and deployment

See `docs/explainers.md` for the reasoning behind each design choice.
