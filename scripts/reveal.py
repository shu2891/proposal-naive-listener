#!/usr/bin/env python3
"""Sequential exposure and append-only observations; not a tool-access sandbox."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value, exclusive=False):
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(data)
    else:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(data, encoding="utf-8")
        temp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def mupdf_module():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def pdf_open(source):
    try:
        mupdf = mupdf_module()
    except ImportError:
        try:
            import pypdfium2
        except ImportError as exc:
            raise ValueError("PDF rendering requires PyMuPDF or pypdfium2 in this Python environment.") from exc
        return "pdfium", pypdfium2.PdfDocument(str(source))
    doc = mupdf.open(str(source))
    if doc.needs_pass:
        doc.close()
        raise ValueError("Password-protected PDF is not supported; supply an unlocked copy.")
    return "mupdf", doc


def inspect_source(source):
    assets = {}
    if source.suffix.lower() == ".pdf":
        backend, doc = pdf_open(source)
        try:
            total = len(doc)
        finally:
            doc.close()
        return "pdf", total, assets
    require(source.suffix.lower() == ".json", "Use a PDF or ordered JSON manifest; render PPTX first.")
    data = read_json(source)
    units = data.get("units") if isinstance(data, dict) else None
    require(isinstance(units, list) and units, "Manifest requires a nonempty units array.")
    for i, unit in enumerate(units, 1):
        require(isinstance(unit, dict), f"Unit {i} must be an object.")
        for key in ("visible", "spoken"):
            require(isinstance(unit.get(key, ""), str), f"Unit {i}: {key} must be text.")
        require(any(unit.get(k) for k in ("visible", "spoken", "image")), f"Unit {i} has no audience input.")
        if unit.get("image"):
            require(isinstance(unit["image"], str), f"Unit {i}: image must be a path.")
            path = (source.parent / unit["image"]).resolve()
            require(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}, f"Unit {i}: use a raster image.")
            require(path.is_file(), f"Missing image for unit {i}.")
            assets[str(i)] = {"path": str(path), "sha256": digest(path)}
    return "json", len(units), assets


def load_state(session):
    state = read_json(session / ".state.json")
    source = Path(state["source"])
    require(source.is_file() and digest(source) == state["sha256"], "Source changed or missing; start a new session.")
    for asset in state["assets"].values():
        path = Path(asset["path"])
        require(path.is_file() and digest(path) == asset["sha256"], "Source image changed or missing; start a new session.")
    return state


def snapshots(session):
    paths = sorted((session / "snapshots").glob("unit-*.json"))
    result = []
    for i, path in enumerate(paths, 1):
        require(path.name == f"unit-{i:04d}.json", "Snapshot ledger is not contiguous.")
        snap = read_json(path)
        require(snap.get("unit") == i, "Snapshot ledger has inconsistent unit numbers.")
        result.append(snap)
    return result


def expose(session, state, number):
    out = session / "revealed" / f"unit-{number:04d}"
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    source = Path(state["source"])
    if state["kind"] == "pdf":
        backend, doc = pdf_open(source)
        target = out / "visible.png"
        try:
            if backend == "mupdf":
                mupdf = mupdf_module()
                doc.load_page(number - 1).get_pixmap(matrix=mupdf.Matrix(1.5, 1.5), alpha=False, annots=False).save(str(target))
            else:
                page = doc[number - 1]
                try:
                    bitmap = page.render(scale=1.5, draw_annots=False)
                    try:
                        bitmap.to_pil().save(target)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            doc.close()
        paths["image"] = str(target)
    else:
        unit = read_json(source)["units"][number - 1]
        for channel in ("visible", "spoken"):
            if unit.get(channel):
                target = out / f"{channel}.md"
                target.write_text(unit[channel], encoding="utf-8")
                paths[channel] = str(target)
        if unit.get("image"):
            asset = Path(state["assets"][str(number)]["path"])
            target = out / ("visible" + asset.suffix.lower())
            shutil.copyfile(asset, target)
            paths["image"] = str(target)
    write_json(out / "exposure.json", {"unit": number, "paths": paths})
    return {"unit": number, "paths": paths}


def text_field(obj, key):
    require(isinstance(obj, dict) and isinstance(obj.get(key), str) and obj[key].strip(), f"{key} must be nonempty text.")


def list_field(obj, key):
    require(isinstance(obj.get(key), list), f"{key} must be an array.")
    return obj[key]


def check_snapshot(snap, session, unit):
    require(isinstance(snap, dict), "Snapshot must be an object.")
    require(type(snap.get("unit")) is int and snap["unit"] == unit, "Snapshot unit must match the pending exposure.")
    for key in ("retelling", "state_reason"):
        text_field(snap, key)
    require(snap.get("state") in {"clear", "provisional", "blocked"}, "Invalid comprehension state.")
    knowledge = list_field(snap, "knowledge")
    for claim in knowledge:
        for key in ("claim", "rationale"):
            text_field(claim, key)
        require(claim.get("basis") in {"explicit", "inferred", "assumed", "unknown"}, "Invalid claim basis.")
        evidence = list_field(claim, "evidence")
        require(claim["basis"] != "explicit" or evidence, "Explicit claims require audience evidence.")
        for ref in evidence:
            require(isinstance(ref, dict), "Evidence must be an object.")
            n = ref.get("unit")
            require(type(n) is int and 1 <= n <= unit, "Evidence refers to an unrevealed unit.")
            require(ref.get("channel") in {"visible", "spoken"}, "Invalid evidence channel.")
            text_field(ref, "anchor")
            paths = read_json(session / "revealed" / f"unit-{n:04d}" / "exposure.json")["paths"]
            available = ref["channel"] in paths or (ref["channel"] == "visible" and "image" in paths)
            require(available, "Evidence refers to an unavailable audience channel.")
    for expectation in list_field(snap, "expectations"):
        require(isinstance(expectation, str) and expectation.strip(), "Expectations must be nonempty text.")
    for assumption in list_field(snap, "assumptions"):
        for key in ("text", "impact"):
            text_field(assumption, key)
    for question in list_field(snap, "questions"):
        for key in ("question", "why"):
            text_field(question, key)
        require(question.get("kind") in {"detail", "ambiguity", "blocker"}, "Invalid question kind.")
        require(type(question.get("ask_now")) is bool, "ask_now must be boolean.")
        if "alternatives" in question:
            require(isinstance(question["alternatives"], list) and all(isinstance(x, str) for x in question["alternatives"]), "alternatives must be text array.")
    for event in list_field(snap, "events"):
        text_field(event, "explanation")
        require(event.get("type") in {"misread_risk", "break", "repair", "revision"}, "Invalid event type.")
        refs = list_field(event, "related_units")
        require(refs and all(type(n) is int and 1 <= n <= unit for n in refs), "Event refers to an unrevealed unit.")
        if event["type"] in {"repair", "revision"}:
            require(any(n < unit for n in refs), "Repair/revision must link an earlier unit.")


def inline(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def project(session, state):
    ledger = snapshots(session)
    if not ledger:
        return
    last = ledger[-1]
    condition = (
        f"模式（操作者聲明）：{state['mode']}；受眾：{inline(state['audience'])}；"
        f"已記錄：{len(ledger)}/{state['total']} 單位。\n\n"
        "此為 AI 模擬；紀錄的猜測／理解狀態不代表真人反應或正確率。\n\n"
    )
    model = ["# 目前理解\n\n", condition, f"截至單位 {last['unit']}：{last['retelling']}\n\n",
             f"狀態：{last['state']}。{last['state_reason']}\n\n"]
    for claim in last["knowledge"]:
        refs = "; ".join(f"單位 {r['unit']} / {r['channel']} / {inline(r['anchor'])}" for r in claim["evidence"])
        model.append(f"- [{claim['basis']}] {inline(claim['claim'])}；依據：{refs or '無頁面依據'}；理由：{inline(claim['rationale'])}\n")
    if last["expectations"]:
        model.append("\n## 當下預期（非設計事實）\n\n")
        model.extend(f"- {inline(x)}\n" for x in last["expectations"])
    assumptions = ["# 猜測歷史\n\n", condition]
    questions = ["# 疑問歷史\n\n", condition]
    timeline = ["# 理解時間軸\n\n", condition, "| 單位 | 當時復述 | 狀態與理由 | 事件 |\n|---|---|---|---|\n"]
    for snap in ledger:
        n = snap["unit"]
        for a in snap["assumptions"]:
            assumptions.append(f"- 單位 {n}：{inline(a['text'])}；影響：{inline(a['impact'])}\n")
        for q in snap["questions"]:
            questions.append(f"- 單位 {n} [{q['kind']}] {inline(q['question'])}；原因：{inline(q['why'])}；當下提問：{q['ask_now']}\n")
            if q.get("alternatives"):
                questions.append(f"  - 當時解讀：{' / '.join(inline(x) for x in q['alternatives'])}\n")
        events = "; ".join(f"{e['type']}（關聯單位 {','.join(map(str, e['related_units']))}）：{inline(e['explanation'])}" for e in snap["events"])
        timeline.append(f"| {n} | {inline(snap['retelling'])} | {snap['state']}：{inline(snap['state_reason'])} | {events or '—'} |\n")
    for name, lines in (("mental-model.md", model), ("assumptions.md", assumptions), ("questions.md", questions), ("comprehension-timeline.md", timeline)):
        (session / name).write_text("".join(lines), encoding="utf-8")


def run(args):
    session = Path(args.session).resolve()
    if args.command == "init":
        require(not session.exists(), "Session already exists; use a new session directory.")
        source = Path(args.source).resolve()
        kind, total, assets = inspect_source(source)
        require(total > 0, "Source has no units.")
        state = {"source": str(source), "sha256": digest(source), "kind": kind, "assets": assets,
                 "total": total, "exposed": 0, "mode": args.mode, "audience": args.audience}
        session.mkdir(parents=True)
        (session / "snapshots").mkdir()
        (session / "revealed").mkdir()
        write_json(session / ".state.json", state)
        return {"session": str(session), "total": total, "mode": args.mode}
    state = load_state(session)
    recorded = len(snapshots(session))
    require(recorded <= state["exposed"] <= min(recorded + 1, state["total"]), "Inconsistent exposure ledger.")
    if args.command == "status":
        return {"total": state["total"], "recorded": recorded, "exposed": state["exposed"],
                "pending": state["exposed"] > recorded, "complete": recorded == state["total"], "mode": state["mode"]}
    if args.command == "next":
        require(recorded == state["exposed"], "Record the pending unit before revealing another.")
        require(recorded < state["total"], "All units are already recorded.")
        result = expose(session, state, recorded + 1)
        state["exposed"] = recorded + 1
        write_json(session / ".state.json", state)
        return result
    if args.command == "current":
        require(state["exposed"] > recorded, "There is no pending unit to re-expose.")
        return expose(session, state, state["exposed"])
    if args.command == "record":
        require(state["exposed"] == recorded + 1, "There is no pending unit to record.")
        snap = read_json(Path(args.snapshot))
        check_snapshot(snap, session, state["exposed"])
        target = session / "snapshots" / f"unit-{state['exposed']:04d}.json"
        write_json(target, snap, exclusive=True)
        project(session, state)
        return {"recorded": state["exposed"], "complete": state["exposed"] == state["total"]}
    if args.command == "rebuild":
        project(session, state)
        return {"recorded": recorded, "rebuilt": True}
    raise ValueError("Unknown command.")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "next", "current", "record", "status", "rebuild"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--session", required=True)
        if name == "init":
            cmd.add_argument("--source", required=True)
            cmd.add_argument("--mode", required=True, choices=("independent", "limited", "contaminated"))
            cmd.add_argument("--audience", default="具一般生活常識、沒有專案背景的成人")
        if name == "record":
            cmd.add_argument("--snapshot", required=True)
    try:
        result = run(parser.parse_args())
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
