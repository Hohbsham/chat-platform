"""
A2A CLI — safe command-line interface for Hermes to manage A2A agents & tasks.
Usage:
  python a2a_cli.py agents              # List online agents
  python a2a_cli.py agents --all        # List all agents
  python a2a_cli.py tasks               # List pending tasks
  python a2a_cli.py tasks --all         # List all tasks
  python a2a_cli.py create --title "..." --desc "..." --caps "cap1,cap2" [--priority high]
  python a2a_cli.py result <task_id>    # Get task result
  python a2a_cli.py chat --sender "..." --msg "..."
  python a2a_cli.py cleanup             # Remove duplicate/offline agents
"""
import json, sys, os, urllib.request

HOST = os.environ.get("A2A_HOST", "http://localhost:8765")

def get(path):
    url = f"{HOST}{path}"
    return json.loads(urllib.request.urlopen(url, timeout=10).read())

def post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

def cmd_agents(args):
    all_agents = get("/api/agents")
    if not args.all:
        all_agents = [a for a in all_agents if a.get("status") == "online"]
    print(f"{'在线' if not args.all else '全部'} Agent: {len(all_agents)} 个")
    print()
    for a in all_agents:
        caps = ",".join(a.get("capabilities", []))
        print(f"  [{a.get('status','?')}] {a['name']:20s} {a.get('agent_id','')[:20]}")
        if caps:
            print(f"       能力: {caps}")

def cmd_tasks(args):
    status = "" if args.all else "?status=pending"
    tasks = get(f"/api/tasks{status}")
    if not isinstance(tasks, list):
        tasks = [tasks] if tasks else []
    print(f"{'待处理' if not args.all else '全部'}任务: {len(tasks)} 个")
    for t in tasks:
        print(f"  [{t.get('status','?')}] {t.get('task_id','')} {t.get('title','')[:60]}")
        if t.get("claimed_by"):
            print(f"       领取: {t['claimed_by']}")
        if t.get("result"):
            print(f"       结果: {t['result'][:120]}")

def cmd_create(args):
    caps = [c.strip() for c in args.caps.split(",")] if args.caps else []
    result = post("/api/tasks", {
        "title": args.title,
        "description": args.desc or "",
        "required_capabilities": caps,
        "priority": args.priority or "normal",
        "creator": "Hermes",
    })
    if result.get("ok"):
        t = result["task"]
        print(f"Created: {t['task_id']} [{t['priority']}] {t['title']}")
    else:
        print(f"Error: {result}")

def cmd_result(args):
    t = get(f"/api/tasks/{args.task_id}")
    if isinstance(t, dict):
        print(f"任务: {t.get('title','?')}")
        print(f"状态: {t.get('status','?')}")
        print(f"领取: {t.get('claimed_by','?')}")
        print(f"完成: {t.get('completed_by','?')}")
        print(f"结果:\n{t.get('result','(无)')}")
    else:
        print(f"Not found: {args.task_id}")

def cmd_chat(args):
    post("/api/send", {"sender": args.sender, "content": args.msg})
    print("OK")

def cmd_cleanup(args):
    """Remove duplicate registrations for the same agent name."""
    agents = get("/api/agents")
    seen = {}
    removed = 0
    for a in agents:
        name = a.get("name", "")
        if name not in seen:
            seen[name] = a
        else:
            # Duplicate! Unregister it
            try:
                post("/api/agents/unregister", {"agent_id": a["agent_id"]})
                removed += 1
                print(f"  Removed duplicate: {name} ({a['agent_id'][:20]})")
            except Exception as e:
                print(f"  Failed: {name} — {e}")
    print(f"\nCleaned up {removed} duplicates. {len(seen)} unique agents remain.")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="A2A CLI for Hermes")
    sp = p.add_subparsers(dest="cmd")

    sp_agents = sp.add_parser("agents")
    sp_agents.add_argument("--all", action="store_true")

    sp_tasks = sp.add_parser("tasks")
    sp_tasks.add_argument("--all", action="store_true")

    sp_create = sp.add_parser("create")
    sp_create.add_argument("--title", required=True)
    sp_create.add_argument("--desc", default="")
    sp_create.add_argument("--caps", default="")
    sp_create.add_argument("--priority", default="normal")

    sp_result = sp.add_parser("result")
    sp_result.add_argument("task_id")

    sp_chat = sp.add_parser("chat")
    sp_chat.add_argument("--sender", required=True)
    sp_chat.add_argument("--msg", required=True)

    sp.add_parser("cleanup")

    args = p.parse_args()
    if args.cmd == "agents":
        cmd_agents(args)
    elif args.cmd == "tasks":
        cmd_tasks(args)
    elif args.cmd == "create":
        cmd_create(args)
    elif args.cmd == "result":
        cmd_result(args)
    elif args.cmd == "chat":
        cmd_chat(args)
    elif args.cmd == "cleanup":
        cmd_cleanup(args)
    else:
        p.print_help()
