from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rule_engine import _overall_drawdown_pct


CASES = [
    ('Trader report', 500, 555, 544.60, 544.60, 'equity', True, 1.8738738739),
    ('Equity trailing off', 500, 555, 544.60, 544.60, 'equity', False, 0.0),
    ('Static ignores peak', 500, 555, 544.60, 544.60, 'static', True, 0.0),
    ('Static below start', 500, 555, 470, 470, 'static', False, 6.0),
    ('Equity trailing below start', 500, 520, 480, 480, 'equity', True, 7.6923076923),
    ('Equity trailing at peak', 500, 560, 560, 560, 'equity', True, 0.0),
]


for name, start, peak, equity, balance, model, trailing, expected in CASES:
    challenge = SimpleNamespace(
        challenge_template=SimpleNamespace(account_size=start, challenge_type='one_phase', phase1_overall_dd_trailing=trailing),
        current_phase=1, starting_balance=start, highest_equity=peak, peak_equity=peak,
        current_equity=equity, current_balance=balance,
    )
    actual, reference, current = _overall_drawdown_pct(challenge, {'overall_dd_type': model, 'overall_dd_trailing': trailing})
    passed = abs(actual - expected) < 0.005
    print(f"{'PASS' if passed else 'FAIL'} {name}: {actual:.2f}% (reference ${reference:.2f}, current ${current:.2f}; expected {expected:.2f}%)")
    if not passed:
        raise SystemExit(1)
