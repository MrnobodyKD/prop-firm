import sqlite3, os
adds = {
    "challenge_template": [
        ("currency", "VARCHAR(10)"), ("no_expiry", "BOOLEAN"),
        ("consistency_enabled", "BOOLEAN"), ("max_single_day_profit_percent", "FLOAT"),
        ("consistency_action", "VARCHAR(20)"), ("first_withdrawal_days", "INTEGER"),
        ("min_payout_percent", "FLOAT"), ("performance_reward_percent", "FLOAT"),
        ("performance_reward_mode", "VARCHAR(30)"), ("max_accounts_per_user", "INTEGER"),
        ("fee_refund_on_pass", "BOOLEAN"), ("refund_policy_text", "TEXT"),
        ("banned_practices", "JSON"), ("news_trading_allowed", "BOOLEAN"),
        ("overnight_trading_allowed", "BOOLEAN"), ("ea_allowed", "BOOLEAN"),
    ],
    "payout": [("crypto_address", "VARCHAR(255)")],
    "coupon": [("currency", "VARCHAR(10)")],
}
for path in ("instance/tragene_funded_new.db", "tragene_funded_new.db"):
    if not os.path.exists(path):
        print("skip (not found):", path)
        continue
    con = sqlite3.connect(path)
    for table, cols in adds.items():
        existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name in existing:
                print(f"{path} {table}.{name} already exists")
            else:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                print(f"{path} {table}.{name} ADDED")
    con.commit()
    con.close()
print("DONE")
