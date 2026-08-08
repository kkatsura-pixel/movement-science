"""
Kinetica 種目データ 機械的検証スクリプト
GitHub Actionsから自動実行される。Claudeの自己申告に依存しない、独立した検証層。
 
使い方：
  SUPABASE_URL, SUPABASE_KEY を環境変数に設定して実行
  python validate_exercises.py
  終了コード0=全件合格、1=不合格あり（CIがこれを検知してビルド/デプロイを失敗させる）
"""
import os
import sys
import re
import json
 
try:
    import requests
except ImportError:
    print("requestsライブラリが必要です: pip install requests")
    sys.exit(1)
 
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
 
MIN_LEN = {
    "overview": 100, "indications": 60, "anatomy": 170, "functional_anatomy": 150,
    "neuroscience": 140, "steps": 140, "cueing": 140, "error_patterns": 200,
}
MIN_TAGS = 8
MIN_BEFORE_AFTER = 5
MIN_PROGRESSIONS = 5
MIN_ERROR_CORR = 5
 
# 仕様書14-1節：ベンチマーク項目の追跡用キーワード（evidence欄で検索）
BENCHMARK_KEYWORDS = {
    "DNS": ["Kobesova", "Kolar"],
    "FMS": ["Cook, G."],
    "NSCA": ["Journal of Strength and Conditioning"],
    "理学療法(PT)": ["Physical Therapy", "Physical Medicine and Rehabilitation"],
    "SFMA": [],  # 未着手（キーワード未定義＝0件が正しい状態）
    "FCS": [],
    "PRI": [],
    "Z-Health": [],
    "JCCA": [],
    "JARTA": [],
}
 
def fetch_all_exercises():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[警告] SUPABASE_URL/SUPABASE_KEY未設定。ローカルJSONファイルがあればそちらを使う運用に切替えてください。")
        sys.exit(1)
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/exercises?select=*", headers=headers)
    resp.raise_for_status()
    return resp.json()
 
def validate(data):
    issues = []
    all_evidence_text = []
 
    for ex in data:
        name = ex.get("name_ja", "（名称不明）")
        domain = ex.get("domain", "") or ""
        is_screening = "スクリーニング系" in domain
 
        for field, minlen in MIN_LEN.items():
            val = ex.get(field) or ""
            if len(val) < minlen:
                issues.append(f"[NG] {name} / {field}: {len(val)}字 (基準{minlen}字以上)")
 
        tags = ex.get("tags") or ""
        tag_count = len([t for t in tags.split(",") if t.strip()])
        if tag_count < MIN_TAGS:
            issues.append(f"[NG] {name} / tags: {tag_count}個 (基準{MIN_TAGS}個以上)")
 
        for field in ["before_exercises", "after_exercises"]:
            val = ex.get(field) or ""
            cnt = len([x for x in val.split(",") if x.strip()])
            if cnt < MIN_BEFORE_AFTER:
                issues.append(f"[NG] {name} / {field}: {cnt}件 (基準{MIN_BEFORE_AFTER}件以上)")
 
        progressions = ex.get("progressions")
        if is_screening:
            if progressions not in (None, ""):
                issues.append(f"[NG] {name} / progressions: スクリーニング系はNULLであるべき")
        else:
            prog_items = re.findall(r'⭐️+\s*[^,]+', progressions or "")
            if len(prog_items) < MIN_PROGRESSIONS:
                issues.append(f"[NG] {name} / progressions: {len(prog_items)}件 (基準{MIN_PROGRESSIONS}件以上)")
 
        ec = ex.get("error_corrections") or ""
        ec_items = [x for x in ec.split(", ") if "→" in x]
        if len(ec_items) < MIN_ERROR_CORR:
            issues.append(f"[NG] {name} / error_corrections: {len(ec_items)}件 (基準{MIN_ERROR_CORR}件以上)")
 
        regressions = ex.get("regressions") or ""
        for letter in ["A（発達）", "B（神経系）", "C（疼痛）", "D（呼吸）", "E（解剖学的制限）"]:
            if letter not in regressions:
                issues.append(f"[NG] {name} / regressions: {letter}欠落")
 
        # related_exercisesのレイヤー接頭辞・「・」区切りチェック
        rel = ex.get("related_exercises") or ""
        if re.search(r'Layer\s*\d', rel):
            issues.append(f"[NG] {name} / related_exercises: レイヤー接頭辞が含まれている（禁止）")
 
        evidence = ex.get("evidence") or ""
        if evidence:
            all_evidence_text.append((name, evidence))
 
    # 文言使い回しチェック（evidence欄の引用元の使い回し）
    evidence_seen = {}
    for name, evidence in all_evidence_text:
        key = evidence.strip()
        if key in evidence_seen:
            evidence_seen[key].append(name)
        else:
            evidence_seen[key] = [name]
    for key, names in evidence_seen.items():
        if len(names) >= 5:
            issues.append(f"[注意] evidence欄の引用元使い回し: 「{key[:50]}...」が{len(names)}種目で完全一致（{', '.join(names[:5])}等）")
 
    # 14-1節ベンチマークカバレッジ集計
    coverage_report = {}
    for benchmark, keywords in BENCHMARK_KEYWORDS.items():
        if not keywords:
            coverage_report[benchmark] = "未着手（対応するキーワード未設定）"
            continue
        count = sum(1 for _, ev in all_evidence_text if any(kw in ev for kw in keywords))
        coverage_report[benchmark] = f"{count}種目で言及"
 
    return issues, coverage_report
 
def main():
    data = fetch_all_exercises()
    print(f"対象種目数: {len(data)}")
    issues, coverage = validate(data)
 
    print("\n=== ベンチマークカバレッジ（14-1節） ===")
    for k, v in coverage.items():
        print(f"  {k}: {v}")
 
    print(f"\n=== 検証結果: NG {len(issues)}件 ===")
    for i in issues:
        print(i)
 
    if issues:
        sys.exit(1)  # CIをここで失敗させる
    else:
        print("全項目合格")
        sys.exit(0)
 
if __name__ == "__main__":
    main()
