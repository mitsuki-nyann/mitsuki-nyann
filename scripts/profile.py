#!/usr/bin/env python3
"""Pixel profile: standard-library-only XP ledger, GitHub importer and SVG renderer."""
import argparse
import base64
from collections import Counter
import copy
import hashlib
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
COLORS = ["#fbfcfe", "#dce7f1", "#577da6", "#3c4e65"]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def instant(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("日時にはタイムゾーンが必要です: " + value)
    return dt.astimezone(timezone.utc)


def validate_config(cfg):
    if type(cfg["xp_per_level"]) is not int or cfg["xp_per_level"] < 1:
        raise ValueError("xp_per_level は1以上の整数にしてください")
    if len(cfg["stats"]) != 6:
        raise ValueError("stats は6項目にしてください")
    for name, rule in cfg["rules"].items():
        if type(rule["xp"]) is not int or rule["xp"] < 0:
            raise ValueError(name + " のxpは0以上の整数にしてください")
        if rule["stat"] not in cfg["stats"]:
            raise ValueError("未知の能力: " + rule["stat"])
    instant(cfg["github"]["since"])
    sources = cfg["github"]["sources"]
    names = [s["repo"].lower() for s in sources]
    if len(names) != len(set(names)):
        raise ValueError("同じリポジトリを複数登録できません")
    for s in sources:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", s["repo"]):
            raise ValueError("repo は owner/name の形式で指定してください")
        if s["mode"] not in ("commits", "prs"):
            raise ValueError("mode は commits または prs です")
        owner, repo = s["repo"].split("/")
        if owner.lower() == repo.lower():
            raise ValueError("プロフィール自身のリポジトリは集計対象にできません")


def score(cfg, events):
    """IDs are stable: identical duplicates are ignored, conflicting ones fail."""
    validate_config(cfg)
    seen, ledger = {}, []
    stats = dict.fromkeys(cfg["stats"], 0)
    for event in events:
        if not isinstance(event.get("id"), str) or not event["id"].strip():
            raise ValueError("活動に空でないidが必要です")
        if event["id"] in seen:
            if seen[event["id"]] != event:
                raise ValueError("異なる内容でidが重複しています: " + event["id"])
            continue
        seen[event["id"]] = event
        instant(event["date"])
        rule = cfg["rules"][event["kind"]]
        stat = event.get("stat", rule["stat"])
        if stat not in stats:
            raise ValueError("未知の能力: " + stat)
        if not isinstance(event.get("title"), str) or not event["title"].strip():
            raise ValueError("活動にtitleが必要です")
        weights = event.get("weights", {stat: 1})
        allocation = allocate(rule["xp"], weights, cfg["stats"])
        for key, amount in allocation.items():
            stats[key] += amount
        ledger.append({**event, "xp": rule["xp"], "stat": stat, "xp_by_stat": allocation})
    total = sum(stats.values())
    step = cfg["xp_per_level"]
    ledger.sort(key=lambda e: (instant(e["date"]), e["id"]))
    return {"total_xp": total, "level": 1 + total // step,
            "level_xp": total % step, "next_level_xp": step,
            "remaining_xp": step - total % step, "stats": stats,
            "events": ledger, **identity(cfg, ledger)}


def allocate(xp, weights, stat_order):
    """Largest remainder allocation: one PR's XP is split, never multiplied."""
    if not isinstance(weights, dict) or not weights:
        raise ValueError("weights は空でない能力と重みの辞書にしてください")
    if any(k not in stat_order or type(v) is not int or v <= 0 for k, v in weights.items()):
        raise ValueError("weights は既知の能力と1以上の整数で指定してください")
    total = sum(weights.values())
    result = {key: xp * weights[key] // total for key in stat_order if key in weights}
    ranking = sorted(result, key=lambda k: -(xp * weights[k] % total))
    for key in ranking[:xp - sum(result.values())]:
        result[key] += 1
    return result


def identity(cfg, ledger):
    settings = cfg.get("growth", {})
    if not settings.get("automatic", False):
        return {"types": cfg["types"], "trait": cfg["trait"], "type_stats": [], "recent_pr_count": 0}
    window = settings.get("recent_prs", 20)
    if type(window) is not int or window < 1:
        raise ValueError("growth.recent_prs は1以上の整数にしてください")
    recent = [e for e in ledger if e.get("source") == "github-pr" or ":pr:" in e["id"]][-window:]
    if not recent:
        return {"types": ["NORMAL"], "trait": "はじまりの一歩 / PRを重ねて成長", "type_stats": [], "recent_pr_count": 0}
    totals = Counter()
    latest = {}
    for index, event in enumerate(recent):
        for key, xp in event["xp_by_stat"].items():
            totals[key] += xp
            if xp > 0:latest[key] = index
    order = list(cfg["stats"])
    top = sorted((k for k, v in totals.items() if v > 0), key=lambda k: (-totals[k], -latest[k], order.index(k)))[:2]
    names = settings.get("type_names", {})
    kinds = Counter(e["kind"] for e in recent)
    dominant = max(kinds, key=lambda k: (kinds[k], max(i for i,e in enumerate(recent) if e["kind"] == k)))
    traits = {"feat": "ものづくり / 新しい機能を形にする", "fix": "しゅうりじょうず / 不具合を直す",
              "refactor": "せいりせいとん / 設計を整える", "test": "たしかめじょうず / 動作を検証する",
              "docs": "つたえじょうず / 学びを共有する", "study": "たんきゅうしん / 知識を深める"}
    return {"types": [names.get(k, k.upper()) for k in top] or ["NORMAL"],
            "trait": traits.get(dominant, cfg["trait"]), "type_stats": top,
            "recent_pr_count": len(recent), "recent_pr_stat_xp": dict(totals)}


def path_stat(filename, source):
    path = filename.lower()
    # Subject folders win over generic document extensions.
    for stat, pattern in [
        ("electric", r"denko|electric|circuit|[/_-]plc|電気|電工|複線図|回路"),
        ("math", r"math|calculus|linear.?algebra|数学|線形|微積|証明|\.tex$"),
        ("test", r"(^|/)(tests?|__tests__)(/|_)|[._](test|spec)\.|(^|/)test_|pytest|playwright|cypress"),
        ("design", r"architecture|design|adr/|設計|要件"),
        ("share", r"(^|/)(docs?|readme)(/|\.|$)|\.(md|rst|pdf)$")]:
        if re.search(pattern, path):return stat
    return source.get("stat", "code")


def classify_pr(pr, filenames, cfg, source):
    labels = [x["name"] for x in pr.get("labels", [])]
    if "xp:skip" in labels:return None
    title = pr["title"]
    category = classify(title, cfg, labels)
    specified = [label[5:] for label in labels if label.startswith("stat:")]
    if any(stat not in cfg["stats"] for stat in specified):
        raise ValueError("stat: ラベルに未知の能力があります")
    match = re.match(r"^[a-z]+\(([a-z]+)\)!?:", title)
    explicit_stat = match[1] if match and match[1] in cfg["stats"] else None
    weights = Counter(path_stat(path, source) for path in filenames)
    if specified:weights = Counter(dict.fromkeys(specified, 1))
    elif explicit_stat:weights = Counter({explicit_stat: 1})
    if not category:
        # An intentional non-learning marker must not become a feature by fallback.
        marker = re.match(r"^([a-z]+)(?:\([^)]*\))?!?:", title)
        if marker and marker[1] in ("chore", "ci", "build", "revert", "release", "qualification"):
            return None
        if any(label.startswith("xp:") for label in labels):
            raise ValueError("未知のxp:ラベルです。種類を確認してください")
        keys = set(weights)
        kind = "test" if keys == {"test"} else "docs" if keys == {"share"} else "study" if keys and keys <= {"math", "electric"} else "feat"
        category = (kind, cfg["rules"][kind]["stat"])
    if not weights:weights = Counter({category[1]: 1})
    primary = max(weights, key=lambda key: (weights[key], -list(cfg["stats"]).index(key)))
    return category[0], primary, dict(weights)


def classify(title, cfg, labels=()):
    """Explicit xp: label overrides conventional title; ambiguous labels fail."""
    kinds = {label[3:] for label in labels if label.startswith("xp:")}
    if "skip" in kinds:
        return None
    if len(kinds) > 1:
        raise ValueError("xp: ラベルは1つだけ指定してください")
    match = re.match(r"^([a-z]+)(?:\(([a-z]+)\))?!?:\s*\S", title)
    kind = next(iter(kinds), None) or (match[1] if match else None)
    # Qualifications and releases are deliberate manual records, not commit labels.
    if kind not in cfg["rules"] or kind in ("qualification", "release"):
        return None
    stat = match[2] if match and match[2] in cfg["stats"] else cfg["rules"][kind]["stat"]
    return kind, stat


class GitHub:
    def __init__(self, token=None):
        self.token = token

    def get(self, path, **query):
        url = "https://api.github.com" + path
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "pixel-profile"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"GitHub API HTTP {exc.code}: {path}（権限・回数制限・repo名を確認）") from None
        except URLError:
            raise RuntimeError("GitHub APIに接続できません。記録は変更しません。") from None

    def pages(self, path, **query):
        for page in range(1, 1001):
            items = self.get(path, per_page=100, page=page, **query)
            yield from items
            if len(items) < 100:
                return
        raise RuntimeError("1000ページを超えました。集計範囲を狭めてください")


def collect(cfg, api, existing):
    """Only public, configured repositories and the configured human actor."""
    validate_config(cfg)
    actor = cfg["github"]["actor"].lower()
    since = instant(cfg["github"]["since"])
    output = {event["id"]: event for event in existing}
    for source in cfg["github"]["sources"]:
        repo, mode = source["repo"], source["mode"]
        prefix = "/repos/" + repo
        metadata = api.get(prefix)
        private_summary = source.get("private_summary", False)
        if metadata.get("private") is not False and not private_summary:
            raise ValueError("公開リポジトリのみ集計できます: " + repo)
        if private_summary and mode != "prs":
            raise ValueError("非公開の集計はPR方式のみ対応しています")
        # Changing source mode after earning XP would count the same work twice.
        other = "pr" if mode == "commits" else "commit"
        if any(key.startswith(f"gh:{repo.lower()}:{other}:") for key in output):
            raise ValueError("集計方式の変更前に、そのrepoの旧記録を整理してください: " + repo)
        if mode == "prs":
            for pr in api.pages(prefix + "/pulls", state="closed", sort="updated", direction="desc"):
                if instant(pr["updated_at"]) < since:
                    break
                if not pr.get("merged_at") or instant(pr["merged_at"]) < since:
                    continue
                user = pr.get("user") or {}
                if user.get("login", "").lower() != actor or user.get("type") == "Bot":
                    continue
                identity = f"gh:{repo.lower()}:pr:{pr['number']}"
                if private_summary:
                    identity = "private:" + hashlib.sha256(identity.encode()).hexdigest()
                if identity in output:
                    continue
                weights = None
                if cfg["github"].get("auto_classify", False):
                    if any(x["name"] == "xp:skip" for x in pr.get("labels", [])):
                        continue
                    files = list(api.pages(prefix + f"/pulls/{pr['number']}/files"))
                    if len(files) >= 3000:
                        raise ValueError("変更ファイルが3000件以上のPRは自動分類できません")
                    category = classify_pr(pr, [f["filename"] for f in files], cfg, source)
                    if category:weights = category[2]
                else:
                    category = classify(pr["title"], cfg, [x["name"] for x in pr.get("labels", [])])
                if not category:
                    continue
                visible = {"title": cfg["stats"][category[1]] + "のPRを完了"} if private_summary else {"title": pr["title"], "url": pr["html_url"]}
                output.setdefault(identity, {"id": identity, "kind": category[0], "stat": category[1],
                    "date": pr["merged_at"], **visible, "source": "github-pr",
                    **({"weights": weights} if weights is not None else {})})
        else:
            for commit in api.pages(prefix + "/commits", author=actor,
                    sha=metadata["default_branch"], since=since.isoformat()):
                user = commit.get("author") or {}
                if user.get("login", "").lower() != actor or user.get("type") == "Bot":
                    continue
                if len(commit.get("parents", [])) > 1:
                    continue
                when = commit["commit"]["committer"]["date"]
                if instant(when) < since:
                    continue
                title = commit["commit"]["message"].splitlines()[0]
                category = classify(title, cfg)
                if not category:
                    continue
                identity = f"gh:{repo.lower()}:commit:{commit['sha']}"
                output.setdefault(identity, {"id": identity, "kind": category[0], "stat": category[1],
                    "date": when, "title": title, "url": commit["html_url"]})
    result = list(output.values())
    score(cfg, result)
    return sorted(result, key=lambda e: (instant(e["date"]), e["id"]))


def sync_config(cfg, read_token, private_repos=""):
    """A missing private-repo credential must not break public rendering."""
    effective = copy.deepcopy(cfg)
    for repo in private_repos.replace("\n", ",").split(","):
        repo = repo.strip()
        if repo:
            effective["github"]["sources"].append({"repo": repo, "mode": "prs", "private_summary": True})
    validate_config(effective)
    pending = sum(1 for source in effective["github"]["sources"] if source.get("private_summary") and not read_token)
    if pending:
        effective["github"]["sources"] = [s for s in effective["github"]["sources"] if not s.get("private_summary")]
    status = "awaiting_token" if pending else "configured" if private_repos.strip() else "awaiting_configuration"
    return effective, {"private_sources_pending": pending, "private_sync": status}


# Original 5x7 bitmap alphabet. SVG rectangles avoid external font dependencies.
FONT_ROWS = {
 "A":"01110/10001/10001/11111/10001/10001/10001", "B":"11110/10001/10001/11110/10001/10001/11110",
 "C":"01111/10000/10000/10000/10000/10000/01111", "D":"11110/10001/10001/10001/10001/10001/11110",
 "E":"11111/10000/10000/11110/10000/10000/11111", "F":"11111/10000/10000/11110/10000/10000/10000",
 "G":"01111/10000/10000/10111/10001/10001/01111", "H":"10001/10001/10001/11111/10001/10001/10001",
 "I":"11111/00100/00100/00100/00100/00100/11111", "J":"00111/00010/00010/00010/10010/10010/01100",
 "K":"10001/10010/10100/11000/10100/10010/10001", "L":"10000/10000/10000/10000/10000/10000/11111",
 "M":"10001/11011/10101/10101/10001/10001/10001", "N":"10001/11001/10101/10011/10001/10001/10001",
 "O":"01110/10001/10001/10001/10001/10001/01110", "P":"11110/10001/10001/11110/10000/10000/10000",
 "Q":"01110/10001/10001/10001/10101/10010/01101", "R":"11110/10001/10001/11110/10100/10010/10001",
 "S":"01111/10000/10000/01110/00001/00001/11110", "T":"11111/00100/00100/00100/00100/00100/00100",
 "U":"10001/10001/10001/10001/10001/10001/01110", "V":"10001/10001/10001/10001/10001/01010/00100",
 "W":"10001/10001/10001/10101/10101/10101/01010", "X":"10001/10001/01010/00100/01010/10001/10001",
 "Y":"10001/10001/01010/00100/00100/00100/00100", "Z":"11111/00001/00010/00100/01000/10000/11111",
 "0":"01110/10001/10011/10101/11001/10001/01110", "1":"00100/01100/00100/00100/00100/00100/01110",
 "2":"01110/10001/00001/00010/00100/01000/11111", "3":"11110/00001/00001/01110/00001/00001/11110",
 "4":"00010/00110/01010/10010/11111/00010/00010", "5":"11111/10000/10000/11110/00001/00001/11110",
 "6":"01110/10000/10000/11110/10001/10001/01110", "7":"11111/00001/00010/00100/01000/01000/01000",
 "8":"01110/10001/10001/01110/10001/10001/01110", "9":"01110/10001/10001/01111/00001/00001/01110",
 "-":"00000/00000/00000/11111/00000/00000/00000", "/":"00001/00001/00010/00100/01000/10000/10000",
 ":":"00000/00100/00100/00000/00100/00100/00000", ".":"00000/00000/00000/00000/00000/00110/00110",
 "+":"00000/00100/00100/11111/00100/00100/00000", "?":"01110/10001/00001/00010/00100/00000/00100"
}


def render(cfg, state, demo=False, avatar_data=None):
    """A DS-era, two-panel summary screen made of portable SVG shapes."""
    moves = cfg.get("moves", [])[:4]
    recent = list(reversed(state["events"]))[:3]
    paper, pale, blue, ink = COLORS
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="1280" viewBox="0 0 960 1280" role="img" aria-labelledby="title desc">',
             '<title id="title">' + escape(cfg["name"]) + ' — PIXEL PROFILE / DS STYLE</title>',
             '<desc id="desc">' + escape(f"レベル {state['level']}、経験値 {state['total_xp']}。" + cfg["bio"]) + '</desc>',
             '<defs><pattern id="grid" width="16" height="16" patternUnits="userSpaceOnUse"><rect width="16" height="16" fill="#e8eff5"/><path d="M 0 16 L 0 0 16 0" fill="none" stroke="#dae3ed" stroke-width="2"/></pattern></defs>']

    def rect(x,y,w,h,c=ink):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')

    def panel(x,y,w,h,fill=paper,stroke="#879bb1"):
        # Cut corners and inset highlights suggest a pixel-era UI.
        parts.append(f'<path d="M{x+8} {y} H{x+w-8} L{x+w} {y+8} V{y+h-8} L{x+w-8} {y+h} H{x+8} L{x} {y+h-8} V{y+8} Z" fill="{fill}" stroke="{stroke}" stroke-width="3"/>')
        rect(x+9,y+4,w-18,2,"#ffffff")

    def pixel(value,x,y,scale=2,c=ink):
        for i,char in enumerate(str(value).upper()):
            if char==" ":continue
            for row,bits in enumerate(FONT_ROWS.get(char,FONT_ROWS["?"]).split("/")):
                for col,bit in enumerate(bits):
                    if bit=="1":rect(x+(i*6+col)*scale,y+row*scale,scale,scale,c)

    def text(value,x,y,size=22,c=ink,limit=36):
        value=str(value)
        if len(value)>limit:value=value[:limit-1]+"…"
        parts.append(f'<text x="{x}" y="{y}" fill="{c}" font-size="{size}" font-family="Noto Sans CJK JP, monospace, sans-serif" font-weight="500">{escape(value)}</text>')

    def bar(x,y,w,ratio,color="#41a9e4",height=14):
        rect(x,y,w,height,"#536679")
        rect(x+2,y+2,w-4,height-4,"#dce2e8")
        fill=int((w-4)*min(1,max(0,ratio)))
        if fill:
            rect(x+2,y+2,fill,height-4,color)
            rect(x+2,y+2,fill,3,"#ffffff66")

    def badge(label,x,y,w,color):
        panel(x,y,w,30,color,color)
        pixel(label[:12],x+12,y+8,2,"#ffffff")

    # Upper summary panel.
    rect(0,0,960,1280,"#303d50")
    rect(8,8,944,608,"url(#grid)")
    rect(8,8,944,53,blue)
    rect(8,57,944,4,"#98b9dc")
    text("つよさを みる",30,44,27,"#ffffff")
    pixel("DEMO / SAMPLE" if demo else "GITHUB PROFILE",704,28,2,"#ffffff")
    for i,label in enumerate(["プロフィール","のうりょく","きろく"]):
        x=26+i*222
        panel(x,76,210,42,"#cf6c79" if i==1 else "#f5f7fa","#974e60" if i==1 else "#a4b4c5")
        text(label,x+20,105,21,"#ffffff" if i==1 else ink)
    pixel("NO. 001",794,88,2,"#61738b")

    panel(26,137,328,335,"#f4f7fa")
    text(cfg["name"],46,177,30,limit=10)
    pixel("LV."+str(state["level"]),239,157,2)
    rect(43,191,294,2,"#c5d3df")
    if avatar_data:
        parts.append(f'<image x="42" y="195" width="296" height="224" href="data:image/png;base64,{avatar_data}" style="image-rendering:pixelated" preserveAspectRatio="xMidYMid meet"/>')
    else:
        pixel("M",156,264,12,"#8298b8")
    type_colors = {"MATH":"#a284bd", "ELECTRIC":"#b7983b", "CODE":"#5989bd", "DESIGN":"#7c85bc", "TEST":"#549783", "SHARE":"#bd7b90", "NORMAL":"#8c929b"}
    for i,type_name in enumerate(state["types"][:2]):
        badge(type_name,44+i*150,424,140,type_colors.get(type_name,"#5989bd"))

    panel(372,137,562,335)
    rect(375,140,556,41,"#d8e4f0")
    text("のうりょく",393,169,22)
    pixel("LEVEL / EXP",758,153,2,"#55748d")
    hues=["#af8abf","#d3af43","#63a4c9","#8494ca","#62b398","#cf889a"]
    for i,(key,value) in enumerate(state["stats"].items()):
        y=189+i*45
        if i%2==0:rect(376,y-1,554,44,"#edf2f6")
        rect(390,y+6,6,22,hues[i])
        text(cfg["stats"][key],411,y+25,22,limit=6)
        pixel("LV"+str(1+value//cfg["xp_per_level"]),535,y+10,2)
        bar(618,y+11,168,(value%cfg["xp_per_level"])/cfg["xp_per_level"],hues[i],12)
        pixel(str(value),815,y+10,2)

    panel(26,490,908,107,"#f7fafc")
    text("けいけんち",45,526,22)
    pixel(str(state["total_xp"])+" EXP",220,507,3)
    text("つぎのレベルまで",590,525,20)
    pixel(str(state["remaining_xp"]),827,508,3)
    badge("EXP",45,546,70,"#557aa0")
    bar(132,551,772,state["level_xp"]/state["next_level_xp"],"#389fde",20)

    # Separation recalls the two displays without drawing a console bezel.
    rect(8,620,944,25,"#263346")
    for x in [435,475,515]:rect(x,629,9,7,"#74879d")

    # Lower panel: traits, four move slots, and recent activity.
    rect(8,650,944,622,"url(#grid)")
    rect(8,650,944,48,blue)
    text("わざと とくせい",30,683,26,"#ffffff")
    pixel("TRAINER MEMO",760,667,2,"#ffffff")
    panel(26,714,908,102)
    badge("ABILITY",43,730,122,"#6887ad")
    text(state["trait"],184,753,22,limit=31)
    text(cfg["bio"],46,790,19,limit=45)

    text("おぼえた わざ / しゅうとくちゅう",28,851,21)
    for i in range(4):
        x=26+(i%2)*464;y=868+(i//2)*90
        move=moves[i] if i<len(moves) else None
        panel(x,y,444,77,"#fdfbf2" if move else "#e8edf3","#a99973" if move else "#acb9c8")
        if move:
            rect(x+4,y+9,7,58,"#d4b455" if move.get("mastered") else "#83a6cc")
            text(move["name"],x+24,y+32,23,limit=17)
            text(move["status"],x+24,y+60,17,"#66778a",limit=24)
            pixel("OK" if move.get("mastered") else "...",x+394,y+51,2,"#6a7f98")
        else:
            text("—",x+24,y+34,24,"#8996a7")
            text("これから おぼえる わざ",x+24,y+60,17,"#8996a7")

    panel(26,1052,908,157)
    rect(29,1055,902,33,"#d8e4f0")
    text("ぼうけんの きろく",46,1080,20)
    if not recent:text("最初の記録を追加して、冒険を始めよう。",46,1134,22)
    for i,event in enumerate(recent):
        y=1122+i*34
        rect(47,y-15,8,8,"#729bc0")
        text(event["title"],68,y,20,limit=33)
        pixel("+"+str(event["xp"])+" EXP",806,y-15,2,"#527b9f")
    text("@"+cfg["handle"],28,1244,18,"#65798d",limit=35)
    pixel("REST DAYS ARE OK",706,1229,2,"#65798d")
    parts.append("</svg>")
    return "\n".join(parts)+"\n"


def build(root, cfg, events, demo=False):
    state=score(cfg,events)
    avatar_data = None
    if cfg.get("avatar"):
        avatar_path = (root / cfg["avatar"]).resolve()
        if not avatar_path.is_relative_to(root.resolve()):
            raise ValueError("avatar はプロジェクト内のPNGを指定してください")
        content = avatar_path.read_bytes()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("avatar はPNG形式が必要です")
        avatar_data = base64.b64encode(content).decode("ascii")
    svg=render(cfg,state,demo,avatar_data)
    dest=root/("demo" if demo else "generated")
    save(dest/"profile.svg",svg)
    save(dest/"stats.json",json_text(state))
    title="見本・架空の活動" if demo else "プロフィール"
    rows="".join(f"<tr><td>{escape(cfg['stats'][key])}</td><td>{value} EXP</td></tr>" for key,value in state["stats"].items())
    save(dest/"preview.html",f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{background:#dce5ef;color:#3c4e65;font-family:monospace;margin:0;padding:24px}}main{{max-width:960px;margin:auto}}img{{width:100%;height:auto}}h1{{font-size:20px}}table{{border-collapse:collapse}}td{{padding:8px 32px 8px 0}}</style>
<main><h1>{escape(cfg['name'])} / {title}</h1><img src="profile.svg" alt="レベル {state['level']}、合計 {state['total_xp']} EXP"><details><summary>数値をテキストで読む</summary><table>{rows}</table></details></main></html>''')
    return state


def demo_events():
    # Explicitly fictional. Never combined with the actual ledger.
    return [{"id":f"demo:{i}","source":"github-pr","kind":kind,"stat":stat,"date":f"2026-11-{i+1:02d}T12:00:00+09:00","title":title}
            for i,(kind,stat,title) in enumerate([
                ("feat","code","【見本】プロフィール編集を作った"),
                ("refactor","design","【見本】保存処理を整理した"),
                ("study","math","【見本】線形代数を学習した"),
                ("study","electric","【見本】複線図を練習した"),
                ("test","test","【見本】保存失敗のテストを書いた"),
                ("test","test","【見本】入力チェックを検証した"),
                ("docs","share","【見本】学んだ仕組みを解説した")])]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["build","sync","add","demo"])
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--id")
    parser.add_argument("--kind")
    parser.add_argument("--stat")
    parser.add_argument("--title")
    parser.add_argument("--date")
    args=parser.parse_args(argv)
    root=args.root.resolve()
    cfg=read_json(root/"profile.json")
    manual=read_json(root/"data/activities.json")
    imported=read_json(root/"data/github.json")
    score(cfg,manual+imported)
    if args.command=="demo":
        result=build(root,cfg,demo_events(),True)
    else:
        if args.command=="sync":
            read_token = os.environ.get("PROFILE_READ_TOKEN")
            effective, sync_status = sync_config(cfg, read_token, os.environ.get("PROFILE_SOURCE_REPOS", ""))
            imported=collect(effective,GitHub(read_token or os.environ.get("GITHUB_TOKEN")),imported)
            score(cfg,manual+imported)
            save(root/"data/github.json",json_text(imported))
            save(root/"generated/sync-status.json",json_text(sync_status))
            if sync_status["private_sources_pending"]:
                print("非公開PRの集計は PROFILE_READ_TOKEN の設定待ちです。画像生成は続行します。")
        if args.command=="add":
            if not all([args.id,args.kind,args.title]):
                parser.error("add には --id --kind --title が必要です")
            if not args.id.startswith("manual:"):
                parser.error("手動記録のidは manual: から始めてください")
            if any(e["id"]==args.id for e in manual+imported):
                parser.error("このidは登録済みです。修正はJSONファイルを編集してください")
            event={"id":args.id,"kind":args.kind,"title":args.title,
                   "date":args.date or datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if args.stat:event["stat"]=args.stat
            manual.append(event)
            score(cfg,manual+imported)
            save(root/"data/activities.json",json_text(manual))
        result=build(root,cfg,manual+imported)
    print(f"Lv.{result['level']} | {result['total_xp']} EXP | NEXT {result['remaining_xp']} EXP")


if __name__=="__main__":
    try:
        main()
    except (ValueError,KeyError,TypeError,RuntimeError,OSError) as exc:
        print(f"エラー: {exc}",file=sys.stderr)
        sys.exit(1)
