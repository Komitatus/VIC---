#!/usr/bin/env python3
"""Render the evidence-backed Wuwa design packet as offline HTML, Markdown and CSV."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path


OFFICIAL = 'https://sdk-prod-cdn-aws.kurogame-service.com/pro/agreement/common/language_ko/product_info.pdf'
EMPIRICAL = 'https://docs.google.com/spreadsheets/d/1DTM0dzTnKdeGyvkgJdPyyp19K_GmOFdovfB1mwN69Es/edit'
STYLE = '''
:root{color-scheme:light;--ink:#172b3a;--muted:#526675;--accent:#156f69;--line:#d9e3e7}
*{box-sizing:border-box}body{margin:0;background:#f3f6f7;color:var(--ink);font:16px/1.7 system-ui,'Malgun Gothic',sans-serif}
main{max-width:1200px;margin:auto;padding:48px 30px 80px;background:white;min-height:100vh}
header{border-top:7px solid var(--accent);padding-top:24px;margin-bottom:35px}h1{font-size:2.1rem;line-height:1.35;letter-spacing:-.04em}
h2{font-size:1.45rem;margin-top:44px;padding-top:12px;border-top:1px solid var(--line)}h3{font-size:1.12rem;margin-top:28px}
a{color:#096c88;text-underline-offset:3px}p,li{max-width:1050px}.meta{color:var(--muted);font-size:.9rem}
.callout{padding:17px 20px;border-left:4px solid var(--accent);background:#eef7f5;margin:22px 0}.warning{background:#fff6e7;border-color:#ad6e16}
.scroll{overflow:auto;margin:18px 0}table{width:100%;border-collapse:collapse;font-size:.89rem}th,td{padding:11px 13px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}th{background:#edf3f5;white-space:nowrap}tr:hover{background:#f7fbfa}
input,select{font:inherit;padding:10px;border:1px solid #9eafb8;border-radius:5px;margin:0 8px 12px 0;max-width:100%}
.filters{padding-top:12px}input{min-width:290px}.badge{display:inline-block;background:#e7f2ef;padding:3px 8px;border-radius:4px}
details{border:1px solid var(--line);padding:12px 16px;margin:14px 0}summary{cursor:pointer;font-weight:600}
code{overflow-wrap:anywhere;background:#eff3f5;padding:2px 4px}footer{color:var(--muted);border-top:1px solid var(--line);margin-top:40px;padding-top:20px}
@media(max-width:700px){main{padding:25px 16px}h1{font-size:1.65rem}th,td{padding:8px}input{min-width:0;width:100%}}
@media print{body,main{background:white}main{max-width:none;padding:0}.filters{display:none}table{font-size:9pt}a{color:inherit}h2{break-after:avoid}tr{break-inside:avoid}}
'''
SCRIPT = '''
document.querySelectorAll('[data-filter-table]').forEach(box=>{
 const table=document.getElementById(box.dataset.filterTable), input=box.querySelector('input'), select=box.querySelector('select');
 const update=()=>{const q=input.value.toLocaleLowerCase(), category=select?select.value:'';let n=0;
 table.querySelectorAll('tbody tr').forEach(row=>{const ok=row.textContent.toLocaleLowerCase().includes(q)&&(!category||row.dataset.category===category);row.hidden=!ok;if(ok)n++;});
 box.querySelector('output').textContent=n+'개 표시';};input.addEventListener('input',update);if(select)select.addEventListener('change',update);update();
});
'''


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Link:
    def __init__(self, text, href):
        self.text, self.href = str(text), str(href).replace(os.sep, '/')


def h(value):
    if isinstance(value, Link):
        return '<a href="' + html.escape(value.href, quote=True) + '">' + html.escape(value.text) + '</a>'
    return html.escape(str(value)).replace('\n', '<br>')


def m(value):
    if isinstance(value, Link):
        href = value.href[:-5] + '.md' if value.href.endswith('.html') else value.href
        return '[' + value.text + '](<' + href + '>)'
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def n(value, digits=2):
    if value is None:
        return '미확인'
    if isinstance(value, int) or float(value).is_integer():
        return f'{value:,.0f}'
    return f'{value:,.{digits}f}'


def items_text(items):
    return '\n'.join(f"{x['name']} [{x['item_id']}] × {'가변·수량 미확인' if x['status']=='client_preview_variable' else n(x['quantity'])}" for x in items) or '연결된 미리보기 없음'


class Doc:
    def __init__(self, title, path, root):
        self.path, self.root = Path(path), Path(root)
        self.title = title
        self.html = ['<header><p class="meta">명조 · 콘텐츠 보상/성장 설계 · 2026-11-18 · 제안 초안</p><h1>' + h(title) + '</h1></header>']
        self.md = ['# ' + title, '\n2026-11-18 · 설치본 3.8.0 · 제안 초안\n']
        if self.path.parent != self.root:
            self.p(Link('전체 기획서로', os.path.relpath(self.root / '명조_콘텐츠별_보상밸런스_기획서.html', self.path.parent)))

    def heading(self, text, level=2):
        self.html.append(f'<h{level}>{h(text)}</h{level}>')
        self.md.append('\n' + '#' * level + ' ' + text + '\n')

    def p(self, text, callout=False):
        self.html.append(('<div class="callout">' if callout else '<p>') + h(text) + ('</div>' if callout else '</p>'))
        self.md.append(('> ' if callout else '') + m(text) + '\n')

    def bullets(self, texts):
        self.html.append('<ul>' + ''.join('<li>' + h(x) + '</li>' for x in texts) + '</ul>')
        self.md.append('\n' + '\n'.join('- ' + m(x) for x in texts) + '\n')

    def table(self, heads, rows, *, table_id=None, categories=None):
        rows = list(rows)
        ident = ' id="' + table_id + '"' if table_id else ''
        body = []
        for i, row in enumerate(rows):
            attr = ' data-category="' + html.escape(categories[i], quote=True) + '"' if categories else ''
            body.append('<tr' + attr + '>' + ''.join('<td>' + h(x) + '</td>' for x in row) + '</tr>')
        self.html.append('<div class="scroll"><table' + ident + '><thead><tr>' + ''.join('<th>' + h(x) + '</th>' for x in heads) + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>')
        self.md.append('\n| ' + ' | '.join(map(m, heads)) + ' |\n| ' + ' | '.join(['---'] * len(heads)) + ' |\n' + '\n'.join('| ' + ' | '.join(map(m, row)) + ' |' for row in rows) + '\n')

    def filters(self, table_id, options=None):
        select = ''
        if options:
            select = '<select aria-label="콘텐츠 유형"><option value="">모든 유형</option>' + ''.join('<option value="' + h(k) + '">' + h(v) + '</option>' for k, v in options) + '</select>'
        self.html.append('<div class="filters" data-filter-table="' + table_id + '"><input aria-label="이름 또는 ID 검색" placeholder="이름 · ID · 지역 검색">' + select + '<output aria-live="polite"></output></div>')

    def details(self, title, callback):
        self.html.append('<details><summary>' + h(title) + '</summary>')
        self.md.append('\n### ' + title + '\n')
        callback()
        self.html.append('</details>')

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prefix = os.path.relpath(self.root, self.path.parent).replace(os.sep, '/')
        content = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + h(self.title) + '</title><link rel="stylesheet" href="' + prefix + '/style.css"><main>' + ''.join(self.html) + '<footer>클라이언트 설정·공식 공개 확률·과거 실측·제안을 구분한 설계 초안입니다. 서버 운영값 변경은 수행하지 않았습니다.</footer></main><script src="' + prefix + '/filter.js"></script></html>'
        self.path.write_text(content, encoding='utf-8')
        self.path.with_suffix('.md').write_text('\n'.join(self.md), encoding='utf-8')


def export_csv(path, heads, rows):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(heads)
        w.writerows(rows)


def profile_table(doc, profile, label):
    def body():
        doc.p('아래 값은 설치본의 보상 설정/미리보기다. 활성 시즌과 실제 지급 완료는 별도 확인 대상이다.')
        if 'budget' in profile:
            doc.p('설정 합계: ' + items_text(profile['budget']))
        doc.table(['목표/난이도', 'Drop ID', '설정 보상'], [(s.get('condition', s.get('target', s.get('level', ''))), s['drop_id'], items_text(s['items'])) for s in profile['steps']])
    doc.details(label, body)


def quantitative_proposals(evidence):
    """Build exact drop-level drafts while preserving each periodic budget."""
    result = []
    def add(cat, scope, step, drop, old, new):
        result.append(dict(category=cat, scope=scope, condition=str(step), drop_id=drop,
                           item_id=3, before=old, after=new, unit='별의 소리', status='proposal'))
    for p in evidence['profiles']['tower']:
        if p['profile_id'] == 13:
            for s in p['steps']:
                old = next(x['quantity'] for x in s['items'] if x['item_id'] == 3)
                add('tower', 'TowerReward 13 / Group 2 / Difficulty 3', s['target'], s['drop_id'], old, 80 if s['target'] <= 24 else 40)
    for p in evidence['profiles']['matrix']:
        if p['cycle_id'] == 9:
            for s in p['steps']:
                old = next((x['quantity'] for x in s['items'] if x['item_id'] == 3), 0)
                proposed = {3761: 75, 3762: 75, 3763: 50, 3764: 25, 3765: 25, 3766: 50}.get(s['drop_id'], old)
                add('matrix', 'Cycle 9 / Levels 17,18', s['condition'], s['drop_id'], old, proposed)
    for p in evidence['profiles']['whimpering']:
        if p['season'] == 25:
            for s in p['steps']:
                old = next(x['quantity'] for x in s['items'] if x['item_id'] == 3)
                proposed = old + (25 if s['drop_id'] == 3546 else -25 if s['drop_id'] == 3551 else 0)
                add('whimpering', 'Season 25', s['condition'], s['drop_id'], old, proposed)
    for p in evidence['profiles']['hologram']:
        old = [next((x['quantity'] for x in s['items'] if x['item_id'] == 3), 0) for s in p['steps']]
        total = sum(old)
        first_half = total // 2
        proposed = [first_half // 2, first_half - first_half // 2] + [(total - first_half) // 4] * 4
        proposed[-1] += total - sum(proposed)
        for s, before, after in zip(p['steps'], old, proposed):
            add('hologram', 'Entrance ' + str(p['entrance_id']), s['level'], s['drop_id'], before, after)
    groups = {}
    for r in result:
        a = groups.setdefault((r['category'], r['scope']), [0, 0])
        a[0] += r['before']; a[1] += r['after']
    for scope, totals in groups.items():
        if totals[0] != totals[1]:
            raise ValueError(f'Budget mismatch: {scope}: {totals}')
    return result, [dict(category=k[0], scope=k[1], before=v[0], after=v[1], passed=v[0] == v[1]) for k, v in groups.items()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True, type=Path)
    ap.add_argument('--sources', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    a.run, a.sources, a.out = a.run.resolve(), a.sources.resolve(), a.out.resolve()
    if a.out.exists():
        ap.error('--out must be a new directory')
    evidence = load(a.run / '콘텐츠_근거.json')
    plans = load(a.run / '기획_정의.json')['plans']
    farm = load(a.run / '파밍계산/결과.json')
    empirical = load(a.sources / '공개_보상요약.json')
    disclosure = load(a.sources / '공식_부옵션확률.json')
    if farm['input_sha256'] != sha(a.run / '파밍_입력.json'):
        raise ValueError('Farming input/result hash mismatch')
    for collection in [evidence['source_files'], load(a.run / '파밍_입력.json')['source_files']]:
        for path, expected in collection.items():
            if sha(path) != expected:
                raise ValueError('Source changed: ' + path)
    catalog = evidence['catalog']
    if len({x['id'] for x in catalog}) != len(catalog):
        raise ValueError('Duplicate guide IDs')
    categories = {p['id']: p for p in plans}
    if set(x['category'] for x in catalog) - set(categories):
        raise ValueError('Category without plan')
    proposals, budget_checks = quantitative_proposals(evidence)
    a.out.mkdir(parents=True)
    (a.out / 'style.css').write_text(STYLE, encoding='utf-8')
    (a.out / 'filter.js').write_text(SCRIPT, encoding='utf-8')
    counts = Counter(x['category'] for x in catalog)
    summary_by_key = {(x['content'], x['group']): x for x in empirical['summaries']}
    source_links = [Link('공식 확률 공시 원문 PDF', OFFICIAL), Link('공개 드롭 실측 원본 시트', EMPIRICAL)]
    status_note = '설치본에 등록된 항목의 기획 명세다. 운영 서버의 현재 개방 여부, 최신 보상 지급 완료, 실제 클리어 시간은 확인하지 않았다.'

    def relative(path, doc):
        return os.path.relpath(path, doc.path.parent)

    def empirical_table(doc, category=None):
        keys = [('tacet', 8, 'exp', 'EXP'), ('forgery', 90, 'equivalent_green', '녹색환산'), ('forgery', 80, 'equivalent_green', '녹색환산'), ('boss', 8, 'material', '돌파 재료'), ('weekly', 8, 'material', '주간 재료'), ('role_exp', 8, 'exp', '공명자 EXP'), ('weapon_exp', 8, 'exp', '무기 EXP')]
        rows = []
        for cat, group, metric, unit in keys:
            if category and cat != category:
                continue
            s = summary_by_key[(cat, group)]; v = s['metrics'][metric]
            ci = v['normal_mean_ci95']
            rows.append([categories[cat]['title'], ('던전 Lv' if cat == 'forgery' else '솔라리스 단계 ') + str(group), s['n'], n(v['mean']) + ' ' + unit, (n(ci[0]) + ' ~ ' + n(ci[1])) if ci else '표본 30 미만: 생략', ', '.join(s['patch_counts']), s['distinct_contributors']])
        doc.table(['대상', '층화 기준', '관측 수', '회당 평균', '평균 95% 구간', '관측 버전', '제보자 수'], rows)
        doc.p('관측은 2.0~2.5 및 버전 미기재 자료다. 현재 3.8 지급량으로 검증된 값이 아니다. 평균 구간은 제보자 군집·패치 변화·시트 필터 편향을 반영하지 않는 정규 근사다.')
        doc.p(Link('실측 원본 및 필터 기준', relative(a.sources / '공개_보상요약.json', doc)))

    def farm_table(doc):
        doc.table(['목표·정책', '후보당 성공 확률', '평균 환산일', 'p50', 'p90', '표본'], [(s['name'], n(s['exact_per_kept_echo']['success_probability_per_candidate'] * 100, 4) + '%', n(s['metrics']['waveplate_equivalent_days']['mean']), n(s['metrics']['waveplate_equivalent_days']['p50']), n(s['metrics']['waveplate_equivalent_days']['p90']), s['samples']) for s in farm['echo_scenarios']])

    def profiles_for(doc, category, entry=None):
        ps = evidence['profiles']
        if category == 'tower':
            for p in ps['tower']:
                profile_table(doc, p, f"설정 프로필 {p['profile_id']} / 난이도 {p['difficulty']} / 보상군 {p['reward_group']}")
        elif category == 'matrix':
            for p in ps['matrix']:
                if p['cycle_id'] == 9:
                    profile_table(doc, p, f"예시 Cycle 9 / Level {p['level_id']} / 난이도 {p['difficulty']}")
            doc.p('시즌 과제 보상은 이 주기 예산과 별도이며, 미확인 활성 주기를 현재 지급 일정으로 변환하지 않는다.')
        elif category == 'whimpering':
            for p in ps['whimpering']:
                if p['season'] in [0, 25]:
                    profile_table(doc, p, f"Season {p['season']} / {'급류·추가' if p['endless'] else '일반'}")
        elif category == 'hologram':
            for p in ps['hologram']:
                if entry is None or p['entrance_id'] in entry.get('hologram_profiles', []):
                    profile_table(doc, p, p['name'] + ' / 입구 ' + str(p['entrance_id']))
        elif category == 'daily':
            profile_table(doc, ps['daily'], '일일 활동도 20/40/60/80/100')
        elif category == 'weekly_rogue':
            w = ps['weekly_rogue']
            doc.p('입장 가이드 외에 검은 꽃 보상 교환 14001011의 행동력 60이 별도 연결된다. 주간 토큰 상한 설정은 3,800이다. 무료 점수 달성과 유료 수령을 합산하지 않는다.')
            doc.table(['예시 주기', '점수', 'Exchange ID', '8단계 미리보기'], [(p['cycle_id'], p['score'], p['exchange_id'], items_text(p['stage8_items'])) for p in w['point_rewards'] if p['cycle_id'] == 2101])
            doc.p('예시 2101의 별의 소리 합계는 100이다. 최신 주기 3801~3806의 LoopId 재사용 관계는 미확인이라 이 합계를 현재 주간 보상으로 일반화하지 않는다.')
        elif category == 'double_reward':
            doc.table(['유형', '회수 설정', '배수', '등록 행 수'], [(t, 3, 2, sum(x['Type'] == t for x in ps['double_reward'])) for t in sorted({x['Type'] for x in ps['double_reward']})])
            doc.p('이벤트 일일 초기화와 대상 콘텐츠 매핑은 실제 이벤트 설정으로 확정해야 한다. 하루 3회가 적용된다는 조건에서 무음구역 4회는 2+2+2+1=7회분이다.')
        elif category == 'rogue_archive':
            doc.table(['과제/결말', 'Drop ID', '설정 미리보기'], [(p['name'], p['Award'], items_text(p['items'])) for key in ['rogue_tasks', 'rogue_end_rewards'] for p in ps[key]])

    for p in plans:
        cat = p['id']
        doc = Doc(p['title'] + ' 보상 밸런스 기획서', a.out / '유형별' / (cat + '.html'), a.out)
        doc.p('범위: ' + str(counts.get(cat, 0)) + '개 가이드 항목. ' + status_note, callout=True)
        doc.heading('목적과 이용 흐름'); doc.p(p['purpose']); doc.p('대상: ' + p['audience']); doc.bullets(p['loop'])
        doc.heading('현황과 병목'); doc.bullets(p['analysis'])
        if cat in ['tacet', 'forgery', 'boss', 'weekly', 'role_exp', 'weapon_exp']:
            empirical_table(doc, cat)
        elif cat == 'shell':
            doc.p('84,000코인/행동력 40은 공개 시트 WAVEPLATE SUMMARY!S28의 작성자 고정 기재값이다. 개별 수령 관측 분포는 확보하지 않았다.')
        profiles_for(doc, cat)
        doc.heading('변경안과 유지 조건'); doc.table(['필드', '기준', '제안', '이유·제약'], p['changes'])
        specific = [r for r in proposals if r['category'] == cat]
        if specific:
            doc.table(['적용 범위', '조건', 'Drop ID', '현재 설정', '제안'], [(r['scope'], r['condition'], r['drop_id'], r['before'], r['after']) for r in specific])
            doc.p('Drop ID는 여러 프로필에서 재사용될 수 있다. 실제 구현은 원본 DropPackage를 일괄 수정하지 않고 해당 범위에 새 보상 ID를 복제·연결하는 안을 우선 검토한다.')
        if cat == 'tacet':
            doc.heading('조건부 파밍 계산'); doc.bullets(farm['assumptions']); farm_table(doc); doc.bullets(farm['limitations'])
        doc.heading('측정 지표와 제안 판정 기준'); doc.table(['지표', '정의', '구분 집단', '제안 기준'], p['kpis'])
        doc.p('판정 기준은 설계 제안이다. 실서비스 이용자 로그로 달성 확인한 결과가 아니다.')
        doc.heading('구현과 검증'); doc.bullets(p['checks'])
        doc.bullets(['공통 지급 로그: claim_id, 계정 익명 키, content_id, instance_id, 난이도, 서버 설정 버전, 보상군, 실제 품목·수량, 배수, 소모 행동력, 최초/반복 구분, 전후 잔액, 시각.', '첫 적용은 해당 콘텐츠/주기 범위에서 전후 코호트를 비교한다. 중복 지급·비용 불일치·설정 예산 초과는 즉시 원인 확인 및 해당 변경 복구 대상이다.', '시간 효율(분당 보상)은 실제 시도·성공·전투 시간을 수집한 뒤 계산한다. 현재 자료에 없는 플레이 시간을 임의로 채우지 않는다.'])
        doc.heading('대상별 명세')
        entries = [e for e in catalog if e['category'] == cat]
        doc.table(['ID', '대상', '지역', '행동력'], [(e['id'], Link(e['name'], '../개별/' + str(e['id']) + '.html'), e['region'], n(e['waveplate_cost'])) for e in entries])
        if cat == 'event_framework':
            doc.p(Link('392개 이벤트 등록부', '../이벤트_등록부.html'))
        doc.heading('근거'); doc.bullets(p['references']); doc.bullets(source_links)
        doc.p(Link('연결된 설치본 근거 JSON', relative(a.run / '콘텐츠_근거.json', doc)))
        doc.write()

    preview_export = []
    for e in catalog:
        p = categories[e['category']]
        doc = Doc(e['name'] + ' · 개별 보상 명세', a.out / '개별' / (str(e['id']) + '.html'), a.out)
        doc.p(status_note, callout=True)
        doc.table(['항목', '값'], [('가이드 ID / 유형', f"{e['id']} / {p['title']}"), ('지역 / 역할', e['region'] + ' / ' + e['description']), ('원본 테이블', e['source_table']), ('입구/던전 ID', e['dungeon_id']), ('LevelPlay ID', ', '.join(map(str, e['level_play_ids'])) or '해당 없음'), ('공명자 ID', e['role_id'] or '해당 없음'), ('해금 조건 ID / PreOpen ID', str(e['unlock_condition']) + ' / ' + str(e['preopen_id'])), ('행동력 / 수령', n(e['waveplate_cost'])), ('연결 방식', '\n'.join(f"Exchange {v['id']}: {v['method']}" + (f" / Instance {v['instance_id']}" if v.get('instance_id') else '') for v in e['exchange_matches']) or '확정 교환 연결 없음')])
        doc.p('행동력 미확인은 무료 판정이 아니다. 해금 ID 0도 서버 계정 조건이 전혀 없다는 증거로 쓰지 않는다.')
        if e['quotas']:
            doc.table(['교환 ID', 'MaxCount', 'SharedId'], [(q['exchange_id'], q['max_count'], q['shared']) for q in e['quotas']])
            doc.p('MaxCount=0의 의미와 리셋 주기는 해당 소비 코드로 확인한다. SharedId가 같은 수령 한도는 콘텐츠별로 중복 계산하지 않는다.')
        doc.heading('콘텐츠 역할과 변경안'); doc.p(p['purpose']); doc.p(Link(p['title'] + ' 상세 기획', '../유형별/' + p['id'] + '.html'))
        doc.table(['필드', '기준', '제안', '이유·제약'], p['changes'])
        doc.heading('현재 단계별 보상 미리보기')
        doc.p('단계 키는 원본 RewardId 맵의 키다. 전투 난이도·계정 단계·데이터 스테이션 레벨을 같은 축으로 합치지 않는다. 수량 0은 가변 표시로 보존한다.')
        doc.table(['단계 키', 'Drop ID', '보상 설정'], [(s['stage'], s['drop_id'], items_text(s['items'])) for s in e['preview_rows']])
        if e['calabash_preview_map']:
            doc.p('데이터 스테이션 참조 맵(별도 축): ' + json.dumps(e['calabash_preview_map'], ensure_ascii=False))
        for s in e['preview_rows']:
            for item in s['items']:
                preview_export.append([e['id'], e['name'], e['category'], s['stage'], s['drop_id'], item['item_id'], item['name'], item['quantity'], item['status']])
        if e['category'] == 'hologram':
            profiles_for(doc, 'hologram', e)
        doc.heading('이 대상에서 검증할 항목'); doc.bullets(p['checks'])
        doc.bullets(['입구·지역·아이템 계열이 이 가이드 ID와 일치하는지 확인한다.', '보상 지급을 실제로 기록해 설정 미리보기와 비교한다. 과거 실측을 이 개별 던전의 3.8 실측으로 표기하지 않는다.', '최초 완료/반복 수령/이벤트 배수/공유 제한별로 로그를 나누어 중복 지급과 과소 지급을 검사한다.'])
        doc.p(Link('전체 연결 근거 및 원본 해시', relative(a.run / '콘텐츠_근거.json', doc)))
        doc.write()

    doc = Doc('기간 콘텐츠 · 이벤트 등록부', a.out / '이벤트_등록부.html', a.out)
    doc.p('392개는 클라이언트 Activity 등록 행 수다. 과거·숨김·준비 데이터가 포함되므로 현재 운영 이벤트 수가 아니다. 아래 항목은 등록부 부록이며 개별 이벤트 전체 보상표를 해석했다는 뜻이 아니다.', callout=True)
    doc.p(Link('기간 콘텐츠 공통 운영 기획', '유형별/event_framework.html'))
    doc.filters('activities')
    doc.table(['Activity ID', '이름', 'Type', '숨김', 'Preview ID', '미리보기'], [(e['id'], e['name'], e['type'], e['hidden'], e['preview_id'], items_text(e['preview_items'])) for e in evidence['activities']], table_id='activities')
    doc.write()

    doc = Doc('서버 보상 테이블 · 연결과 검증 명세', a.out / '서버테이블_설계.html', a.out)
    doc.p('서버가 최종 결과를 보내면서 보상 설정을 테이블로 관리하는 구조는 가능하다. 다만 명조 서버의 실제 내부 테이블을 확보한 것은 아니다. 이번에 확인한 것은 클라이언트의 비용·미리보기 테이블과 서버가 보낸 품목·수량·부옵션 결과를 소비하는 코드다.', callout=True)
    doc.table(['구분', '확인/제안 내용'], [('설치본에서 확인', '가이드/입구 → InstanceDungeon.RewardId → ExchangeReward.Cost 및 단계별 RewardId → DropPackage 미리보기'), ('지급 결과 수신 확인', '22096 알림 → ItemHintController → OnItemRewardNotify. ItemRewardController가 L8n(품목), m9n(수량), b9n(인스턴스)를 사용. 별도 18089 획득 알림도 수량을 수신.'), ('튜닝 결과 수신 확인', 'RequestPhantomIdentify 26204 → xPs 적용 → PhantomDataBase.UpdateData에서 Wws 부옵션 수신'), ('확보하지 않은 것', '서버의 최종 보상 풀, 가중치 테이블, 랜덤 생성/보정 구현, 계정별 실시간 적용 설정'), ('외부 자료로 보완', '공식 부옵션 공시 및 공개 지급 관측. 서버 테이블 원본 추출과는 출처가 다름')])
    doc.heading('개발용 제안 데이터 계약')
    doc.p('아래는 보상 기획을 구현하기 위한 제안 스키마다. 명조 서버를 역공학해 확인한 테이블명이 아니다.')
    schema = [('content_reward_rule', 'content_id, instance_id, difficulty, account_phase, config_version', '콘텐츠·난이도·서버 설정 버전 별도 키'), ('entry_cost', 'currency_id, cost, charge_timing, refund_rule', '입장/성공/수령 중 비용 발생 시점 명시'), ('claim_limit', 'shared_group, max_claims, reset_kind, reset_timezone', '주간 공유 횟수와 일일 배수 횟수를 분리'), ('reward_pool', 'pool_id, roll_count, selection_mode, pity_rule_id', '확정/가중/비복원 추첨을 명시'), ('reward_entry', 'pool_id, item_id, min_qty, max_qty, weight, quantity_rule', '품목 선택 확률과 선택 후 수량 분포를 분리'), ('reward_override', 'content_scope, start_at, end_at, multiplier, quota', '이벤트 배수·기간·대상 제한'), ('claim_ledger', 'claim_id, rule_version, drawn_items, spent_cost, before_after_balance', '중복 청구 방지 및 잔액 보존 검증'), ('echo_roll', 'echo_id, slot, previous_types, chosen_type, value, rule_version', '이미 활성화된 종류 제외 및 실제 수치 확률 검증')]
    doc.table(['제안 테이블', '핵심 필드', '목적'], schema)
    doc.heading('확률·지급 검증')
    doc.bullets(['보상량 분포는 같은 회차의 전체 보상 묶음을 보존한다. 아이템별 독립 추첨으로 쪼개면 공동 발생 관계가 바뀐다.', '튜닝은 성공한 에코만 모으지 않고 모든 시도·이전 옵션·슬롯·실제 수치를 기록한다.', '버전·콘텐츠·난이도·배수별로 층화하고, 참여자 단위 군집을 보존해 신뢰구간을 계산한다.', '현재 시뮬레이션의 p90은 모델 내 꼬리 지표다. 설정 오차나 표본 불확실성까지 포함하는 예측 구간은 아니다.'])
    doc.bullets(source_links); doc.write()

    doc = Doc('명조 콘텐츠별 보상·성장 밸런스 기획서', a.out / '명조_콘텐츠별_보상밸런스_기획서.html', a.out)
    doc.p('20개 유형별 기획서 · 209개 개별 가이드 명세 · 392개 이벤트 등록부. 실제 설치본 3.8.0의 설정을 기준으로 공식 확률과 과거 공개 실측을 연결했다. 제안 수치는 실서비스에 적용하지 않았다.', callout=True)
    doc.heading('이번 기획의 핵심 결정')
    doc.bullets(['무음구역: 8단계 튜너 20→24개를 제안한다. +10 선별 쌍크리 1개에 필요한 재화는 평균 3.56→3.24, p90 6.58→5.58 자연 회복 환산일이다.', '주기 도전: 역경의 탑 800, 예시 해역 시즌 800, 예시 매트릭스 주기 400의 별의 소리 총량을 유지하면서 진입 구간으로 일부 보상을 이동한다.', '응소의 영역: Lv80에 동일 계열 녹색 재료 3개 확정 추가를 제안한다. 과거 실측 평균 34.90→37.90 녹색환산, 약 +8.6%다. Lv90은 유지한다.', '주간 도전·강적·EXP·코인·일일 활동: 공급을 일괄 상향하지 않고 공유 한도, 부족 재화 안내, 최신 버전 지급 검증을 우선한다.'])
    doc.heading('근거의 종류와 적용 범위')
    doc.table(['종류', '이번에 확보한 것', '해석 범위'], [('설치본', '기존 96개 테이블 + 추가 등록부 일치 173개 테이블, 가이드 209개', '비용·성장·미리보기·보상 연결. 활성 서버 상태는 별도'), ('공식 공개', '13개 부옵션 종류와 종류별 수치 확률', '확률 공시 기준의 일반 튜닝 계산'), ('공개 실측', '채택 7,614개 지급 관측, 2.0~2.5 및 일부 버전 미기재', '3.8 현재 지급량 검증 없이 역사적 기준으로 사용'), ('작성자 고정 기재', '튜너 20개, 코인 영역 84,000 등', '개별 지급 분포로 검증한 관측과 구분'), ('설계 제안', '수급·구간 재분배와 KPI 목표', '운영 적용 및 효과 검증 전 초안')])
    doc.bullets(source_links)
    doc.p(Link('서버 테이블 관리와 클라이언트 수신의 차이', '서버테이블_설계.html'))
    doc.heading('공개 지급 실측 요약'); empirical_table(doc)
    doc.heading('공식 부옵션 확률과 성장 비용')
    doc.p('공식 공시에서 일반 튜닝은 13개 종류를 동일 확률로 선택하며 이미 활성화된 종류를 제외한다. 5슬롯에 쌍크리가 포함될 확률은 C(11,3)/C(13,5)=12.8205%다. 중간 폐기 정책은 후보당 완성 확률과 재화 비용을 함께 바꾼다.')
    doc.p('5성 에코 +25의 누적 비용은 EXP 142,600, 레벨업·튜닝 코인 24,260, 특급 튜너 50개다. 실패품은 EXP 75%, 튜너 30% 정수 내림 환급을 적용했다.')
    doc.details('공식 수치별 확률 13종 전체', lambda: doc.table(['종류', '수치', '공개 확률(%)'], [(s['name_ko'], ', '.join(n(v, 1) for v in s['values']), ', '.join(str(p) for p in s['published_percent'])) for s in disclosure['substats'].values()]))
    doc.p(disclosure['normalization'])
    doc.heading('조건부 에코 파밍 기간')
    doc.p('유효한 세트·주옵션의 에코 후보를 충분히 보유하고, 시작 재고는 0인 조건이다. 표의 일수는 소모 행동력÷240이다. 후보 획득·전투·해금·접속 일정과 다른 콘텐츠 소비를 포함한 실제 달력상 파밍 기간이 아니다.', callout=True)
    farm_table(doc)
    doc.details('계산 가정과 한계 전체', lambda: doc.bullets(farm['assumptions'] + farm['limitations']))
    doc.table(['목표 정책', '후보 기대 개수', '순소모 EXP 기대값', '순소모 튜너 기대값', '코인 기대값'], [(s['name'], n(s['exact_per_kept_echo']['expected_candidates']), n(s['exact_per_kept_echo']['expected_net_xp']), n(s['exact_per_kept_echo']['expected_net_tuners']), n(s['exact_per_kept_echo']['expected_coins'])) for s in farm['echo_scenarios'] if s['keep'] == 1 and s['tuners_per_claim'] == 20])
    doc.p('위 기대값은 상태 전이의 정확 계산이다. 파밍 일수는 재화 잔액과 수령 단위를 반영한 모의 계산이라 평균 비용을 평균 보상으로 단순 나눈 값과 다르다. +10/+15 선별은 해당 시점까지 유효 크리티컬이 없으면 폐기하고 목표가 불가능해져도 즉시 폐기한다.')
    doc.p('수령 정책은 EXP·튜너 부족 시 무음구역, 코인만 부족할 때 코인 영역을 즉시 수령하는 방식이다. 전체 과정을 미리 계획한 최소 행동력 해법은 아니다. EXP는 합산 가능한 자원으로 계산하며 개별 재료 초과 투입과 옵션 수치 간 미공개 상관관계는 모델링하지 않았다.')
    doc.heading('다른 성장 재료의 단독 수급 기준')
    doc.table(['목표', '평균 수령 횟수', '횟수 p50 / p90', '평균 행동력 환산일', '환산일 p90'], [(s['name'], n(s['claims']['mean']), n(s['claims']['p50']) + ' / ' + n(s['claims']['p90']), n(s['waveplate_equivalent_days']['mean']), n(s['waveplate_equivalent_days']['p90'])) for s in farm['material_scenarios']])
    doc.p('주간 재료 12개는 4회 수령이므로 공유 주 3회 조건에서 최소 2개 수령 주기에 걸친다. 표의 행동력 1일분을 실제 1일 완료로 읽으면 안 된다. 캐릭터/무기 EXP와 돌파 재료는 각각 단독 수급 사례이며 전체 육성 기간으로 단순 합산하지 않는다.')
    doc.heading('20개 유형별 기획서')
    doc.table(['유형', '개별 가이드 수', '설계 방향'], [(Link(p['title'], '유형별/' + p['id'] + '.html'), counts.get(p['id'], 0), p['purpose']) for p in plans])
    doc.heading('209개 던전·콘텐츠 개별 명세')
    doc.p(status_note)
    doc.filters('catalog', [(p['id'], p['title']) for p in plans if counts.get(p['id'])])
    doc.table(['가이드 ID', '대상', '유형', '지역', '행동력/수령'], [(e['id'], Link(e['name'], '개별/' + str(e['id']) + '.html'), e['category_name'], e['region'], n(e['waveplate_cost'])) for e in catalog], table_id='catalog', categories=[e['category'] for e in catalog])
    doc.p(Link('392개 기간 이벤트 등록 항목 보기', '이벤트_등록부.html'))
    doc.heading('검토와 재현 자료')
    doc.p('6관점 자체 검토이며 독립 에이전트 검토는 아니다. 실제 활성 시즌·실측 최신성·후보 획득률이 남아 있으므로 서비스 효과 확정 판정은 하지 않는다.')
    doc.table(['자료', '내용'], [(Link('보상 변경안 CSV', '보상_변경안.csv'), f'{len(proposals)}개 Drop 연결 단위의 제안; {len(budget_checks)}개 예산 보존 범위 검증'), (Link('단계별 미리보기 CSV', '개별_보상미리보기.csv'), '원본 가이드와 단계·품목·수량·가변 상태'), (Link('기획 정의 JSON', relative(a.run / '기획_정의.json', doc)), '목적·흐름·변경·KPI·검증'), (Link('파밍 입력 JSON', relative(a.run / '파밍_입력.json', doc)), '공식 확률·실측 묶음·비용·시드·원본 해시'), (Link('파밍 계산 결과', relative(a.run / '파밍계산/결과.json', doc)), '정확 기대값 및 9개 에코·5개 재료 시나리오'), (Link('생성·검증 명세', '생성_명세.json'), '범위·해시·예산 검사')])
    doc.write()

    export_csv(a.out / '보상_변경안.csv', ['category', 'scope', 'condition', 'drop_id', 'item_id', 'before', 'after', 'unit', 'status'], [[r[k] for k in ['category', 'scope', 'condition', 'drop_id', 'item_id', 'before', 'after', 'unit', 'status']] for r in proposals])
    export_csv(a.out / '개별_보상미리보기.csv', ['guide_id', 'name', 'category', 'stage_key', 'drop_id', 'item_id', 'item_name', 'preview_quantity', 'status'], preview_export)
    export_csv(a.out / '콘텐츠_목록.csv', ['guide_id', 'name', 'category', 'region', 'waveplate_cost', 'source_table'], [[e[k] if e[k] is not None else '' for k in ['id', 'name', 'category', 'region', 'waveplate_cost', 'source_table']] for e in catalog])
    export_csv(a.out / '이벤트_등록부.csv', ['activity_id', 'name', 'type', 'hidden', 'preview_id', 'status'], [[e[k] for k in ['id', 'name', 'type', 'hidden', 'preview_id']] + ['installed_registration_not_live_state'] for e in evidence['activities']])
    save_json(a.out / '변경안_1.json', {'status': 'proposal_draft', 'rows': proposals, 'budget_checks': budget_checks})
    manifest = {'status': 'generated', 'review_mode': 'self', 'counts': {'plans': len(plans), 'guide_specs': len(catalog), 'activities': len(evidence['activities']), 'proposal_rows': len(proposals), 'budget_checks': len(budget_checks)}, 'input_hashes': {str(p): sha(p) for p in [a.run / '기획_정의.json', a.run / '콘텐츠_근거.json', a.run / '파밍_입력.json', a.run / '파밍계산/결과.json', a.sources / '공개_보상요약.json', a.sources / '공식_부옵션확률.json', Path(__file__).resolve()]}, 'budget_checks': budget_checks, 'outputs': {str(p.relative_to(a.out)): sha(p) for p in sorted(a.out.rglob('*')) if p.is_file()}}
    save_json(a.out / '생성_명세.json', manifest)
    print(json.dumps({'output': str(a.out), 'counts': manifest['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
