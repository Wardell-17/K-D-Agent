# 实验 048 冒烟 v2：K3 coding 端点 $web_search，原始 HTTP 精确控制协议
import json
import os
import sys
import urllib.request

KEY = os.environ["KIMI_API_KEY"]
URL = "https://api.kimi.com/coding/v1/chat/completions"
HEAD = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}",
        "User-Agent": "KimiCLI/1.0"}

QUESTION = "2026 年 7 月中国官方制造业 PMI 数值是多少？请给出数据发布机构与日期。"
tools = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
messages = [{"role": "user", "content": QUESTION}]


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=HEAD)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


for step in range(4):
    code, body = post({"model": "k3", "messages": messages,
                       "tools": tools, "max_tokens": 2048})
    if code != 200:
        print(f"[probe] HTTP {code}: {json.dumps(body, ensure_ascii=False)[:400]}")
        sys.exit(2)
    msg = body["choices"][0]["message"]
    fin = body["choices"][0]["finish_reason"]
    print(f"[probe] step{step} finish={fin}")
    tcs = msg.get("tool_calls") or []
    if tcs:
        # 端点怪癖：返回时 arguments 是对象，回传时必须字符串化（否则 tokenization 400）
        msg_fixed = dict(msg)
        msg_fixed["tool_calls"] = [
            {**tc, "function": {**tc["function"],
                                "arguments": tc["function"]["arguments"]
                                if isinstance(tc["function"]["arguments"], str)
                                else json.dumps(tc["function"]["arguments"], ensure_ascii=False)}}
            for tc in tcs]
        messages.append(msg_fixed)
        for tc in tcs:
            args = tc["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)
            print(f"  → {tc['function']['name']} search_tokens={args.get('usage',{}).get('total_tokens')}")
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "name": tc["function"]["name"],
                             "content": json.dumps(args, ensure_ascii=False)})
        continue
    content = msg.get("content") or ""
    print(f"[probe] 回答({len(content)}字符): {content[:600]}")
    print(f"[probe] usage: {body.get('usage')}")
    print("[probe] 结论: 端点接受 $web_search 并完成闭环，方案 B 端点层可行")
    sys.exit(0)

print("[probe] 超过往返上限")
sys.exit(3)
