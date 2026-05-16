"""CodexTool — ChatGPT 注册 & Codex Token 获取

Usage:
  python main.py register              # 只注册
  python main.py login                 # 只登录（需 --phone --password）
  python main.py all                   # 注册 + 登录（默认）
  python main.py all --count 3         # 批量
"""
import argparse, json, sys, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

OUT_DIR = Path(__file__).parent


def save_json(data, subdir, identifier=None):
    """Save data to {subdir}/chatgpt_{identifier}_{timestamp}.json"""
    d = OUT_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    ident = (identifier or data.get("phone", "unknown")).replace("+", "")
    ts = int(time.time())
    fname = d / f"chatgpt_{ident}_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {fname}")
    return fname


def cmd_register(args):
    """只注册"""
    from chatgpt_register import run_registration

    account, sd = run_registration()
    if account:
        result = {"success": True, **account}
        save_json(result, "success")
        print(f"\n  Phone:    {account['phone']}")
        print(f"  Password: {account['password']}")
        print(f"  Name:     {account.get('name','')}")
    else:
        fail = {"success": False, "error": "registration failed",
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        save_json(fail, "fail")
        sys.exit(1)


def cmd_login(args):
    """只登录"""
    from codex_login import login

    try:
        result = login(args.phone, args.password)
        # Read the saved token file and also save to success/ for consistency
        email = result.get("_email", "")
        data = {
            "success": True,
            "phone": args.phone,
            "password": args.password,
            "email": email,
            "token": {k: v for k, v in result.items() if k != "_email"},
        }
        save_json(data, "success")
    except Exception as e:
        fail = {"success": False, "phone": args.phone, "error": str(e),
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        save_json(fail, "fail")
        sys.exit(1)


def cmd_all(args):
    """注册 + 登录"""
    from chatgpt_register import run_registration

    t_start = time.time()
    results = []
    for i in range(args.count):
        print(f'\n{"#" * 50}\n  [{i+1}/{args.count}]\n{"#" * 50}')

        try:
            account, sd = run_registration()
        except Exception as e:
            fail = {"success": False, "error": str(e),
                    "traceback": traceback.format_exc(),
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            save_json(fail, "fail")
            results.append(fail)
            continue

        if not account:
            fail = {"success": False, "error": "registration failed",
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            save_json(fail, "fail")
            results.append(fail)
            continue

        # Save registration success
        reg_result = {"success": True, **account}
        save_json(reg_result, "success")

        # Codex login
        print(f'\n  Logging into Codex...')
        try:
            from chatgpt_register import login_codex
            token = login_codex(account["phone"], account["password"], sentinel_data=sd)
            email = token.get("_email", "")
            # Merge email into result
            reg_result["email"] = email
            reg_result["token"] = {k: v for k, v in token.items() if k != "_email"}
            # Re-save with token info
            save_json(reg_result, "success")
            results.append(reg_result)
            print(f"  Email: {email}")
        except Exception as e:
            print(f"  Codex login failed: {e}")
            traceback.print_exc()
            # Still save the registration success (no token)
            results.append(reg_result)

    success = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success
    total_t = time.time() - t_start
    print(f'\n  Done. {success} succeeded, {fail_count} failed.  Total: {total_t:.1f}s')

    # Print summary
    for r in results:
        if r.get("success"):
            print(f"  + {r.get('phone','?')} / {r.get('password','?')} / {r.get('email','?')}")


def main():
    parser = argparse.ArgumentParser(description="CodexTool — ChatGPT 注册 & Codex Token")
    sub = parser.add_subparsers(dest="command")

    p_reg = sub.add_parser("register", help="只注册新 ChatGPT 账号")
    p_reg.set_defaults(func=cmd_register)

    p_login = sub.add_parser("login", help="只登录 Codex（需已有账号）")
    p_login.add_argument("--phone", required=True)
    p_login.add_argument("--password", required=True)
    p_login.set_defaults(func=cmd_login)

    p_all = sub.add_parser("all", help="注册 + 登录一条龙（默认）")
    p_all.add_argument("--count", type=int, default=1, help="注册数量")
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    if not args.command:
        args.count = 1
        cmd_all(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
