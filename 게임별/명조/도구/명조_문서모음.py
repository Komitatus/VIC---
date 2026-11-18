#!/usr/bin/env python3
"""Create separate planning, analysis and proposal documents from verified Wuwa evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil

GENERATOR = Path(__file__).with_name('명조_기획서.py')
spec = importlib.util.spec_from_file_location('wuwa_report_components', GENERATOR)
components = importlib.util.module_from_spec(spec)
spec.loader.exec_module(components)
Link, n, items_text = components.Link, components.n, components.items_text


MODELS = {
 'forgery': ('M01', '동일 계열 재료 가치와 정지시간', 'G = g₁ + 3g₂ + 9g₃ + 27g₄; N = min{n: Σ Gᵢ ≥ G목표}', '등급별 수량을 같은 단위로 바꾼 뒤 목표량을 넘는 첫 수령 횟수를 계산한다. 서로 다른 재료 계열은 합치지 않는다.', 'Lv80 확정 녹색 +3은 모든 관측 묶음의 G에 3을 더한다. Lv90과 확률 가중치는 유지한다.', '재료 등급별 독립 추첨으로 바꾸면 공동 드롭 분포가 달라진다.'),
 'role_exp': ('M02', 'EXP 공급과 복수 재화 성장 조건', 'N = min{n: Σ EXPᵢ ≥ EXP부족}; 성장 가능 ⇔ 모든 재화 r에 대해 Bᵣ ≥ Cᵣ', '필요 EXP까지의 수령 횟수와 돌파·코인 충족 여부를 별도로 관리한다.', 'EXP를 일괄 상향하지 않고 현재 레벨·목표·재고에서 부족량을 계산해 다음 콘텐츠를 안내한다.', '돌파 해금과 코인 부족을 EXP 기간에 숨기지 않는다.'),
 'weapon_exp': ('M02', '무기 EXP·코인·돌파의 동시 제약', '부족ᵣ = max(0, 목표비용ᵣ − 재고ᵣ); N_EXP = min{n: Σ EXPᵢ ≥ 부족_EXP}', '무기 강화 가능 조건은 가장 늦게 충족되는 자원에 좌우된다.', '작은 표본의 평균 차이만으로 난이도별 보상을 뒤집지 않고 동일 버전 관측을 추가한다.', '표본 34회의 평균을 서버 고정값으로 취급하지 않는다.'),
 'shell': ('M03', '공유 코인 예산과 예약 비용', 'B다음 = B현재 + 수입 − 성장소모 − 기타소모; 예약 = Σ 목표별 코인', '여러 성장 목표가 같은 잔액을 중복 사용한다고 계획하지 않도록 한다.', '목표별 예약과 남은 가용 잔액을 분리해 보여 주고, 현행 지급 확인 후 공급 변경을 검토한다.', '튜너·EXP 환급과 코인 환급을 같은 비율로 적용하지 않는다.'),
 'boss': ('M04', '변동 수량 재료의 목표 도달', 'N = min{n: Σ Xᵢ ≥ 46}; E[N]은 일반적으로 46/E[X]와 다르다', '마지막 수령의 초과량 때문에 평균 드롭량으로 나눈 값과 실제 횟수 평균이 달라진다.', '4~5개 관측 범위의 좁은 변동은 유지하고 목표 재료와 보스 연결을 명확히 한다.', '비슷한 이름의 다른 돌파 재료를 합산하지 않는다.'),
 'weekly': ('M05', '공유 주간 쿼터', '필요 수령 = ceil(목표재료/회당재료); 필요 수령주기 = ceil(필요 수령/공유쿼터)', '12개/3개=4회이며 주 3회 공유 조건이면 두 수령 주기에 걸친다.', '보스별 화면에 계정 공통 잔여 횟수와 목표 재료까지 필요한 수령 주기를 표시한다.', '두 주기를 14일로 단정하지 않는다. 시작 시각과 리셋 경계에 따라 달라진다.'),
 'tacet': ('M06', '비복원 튜닝·중간 선별·환급', 'p(k) = C(13−k,5−k)/C(13,5); E[후보] = 1/p정책; E[순비용] = E[시도 순비용]/p정책', '종류 확률과 수치 확률을 분리하고 중간 폐기로 바뀐 성공률·환급 비용을 함께 계산한다.', '8단계 튜너를 24개로 제안하되 EXP·입장비·부옵션 확률은 유지한다.', '후보 무제한 가정과 실제 세트·주옵션 후보 획득 시간을 구분한다.'),
 'tower': ('M07', '점수 구간별 보상 함수', 'B(s) = Σ rᵢ·I(s≥tᵢ); 총량 = Σ rᵢ; 기대 지급 = Σ rᵢ·P(S≥tᵢ)', '최대 보상 예산과 이용자 분포에 따른 실제 지급량은 다른 지표다.', 'Group2/Difficulty3의 앞 8구간을 80, 뒤 4구간을 40으로 배치해 총 800을 유지한다.', '구버전 30별과 36별 프로필을 동시에 정기 보상으로 합치지 않는다.'),
 'whimpering': ('M07', '두 도전 구간의 분리 보상', 'E[지급] = Σ 일반 rᵢqᵢ + Σ 추가 rⱼqⱼ; ΔE = 25(q일반첫목표 − q추가첫목표)', '일반과 추가 도전의 접근률 차이를 별도 관측한다.', '예시 Season25의 일반 첫 구간 +25, 추가 첫 구간 −25로 650/150을 제안한다.', 'Season0 최초 보상과 반복 시즌 예산을 구분한다.'),
 'matrix': ('M08', '점수·파티 수의 다중 조건 보상', 'B = Σ 점수 rᵢI(S≥tᵢ) + Σ 파티수 uⱼI(K≥kⱼ); K = Σ I(파티점수≥5000)', '최고 점수와 유효 파티 수를 서로 다른 성과 지표로 유지한다.', '안정 프로토콜에 50을 이동하고 확장 점수 구간에서 50을 줄인다. 3/4개 파티 보상은 유지한다.', '37,000/58,000점 보상에 별의 소리가 있다고 가정하지 않는다.'),
 'hologram': ('M09', '최초 클리어 보상과 학습 진입', 'B계정 = Σ 난이도 rᵢ·I(해당 난이도 최초 수령); Σ rᵢ = 입구별 기존 총량', '재도전과 최초 수령을 분리해 숙련 시도가 반복 성장 공급으로 바뀌지 않게 한다.', '별의 소리의 50%를 첫 두 난이도에, 나머지를 네 난이도에 배치한다.', '입구별 총량이 같다고 가정하지 말고 개별 프로필을 검사한다.'),
 'nightmare': ('M10', '유효 에코 후보 생산성', '후보 생산성 = 목표 세트·주옵션을 동시에 만족한 수 / 실제 소요 분', '에코 총 획득량보다 육성 가능한 후보의 공동 조건을 기준으로 비교한다.', '후보 확률을 임의로 조정하지 않고 종류·세트·주옵션·시간을 함께 기록한다.', '세트 확률과 주옵션 확률의 독립성을 관측 없이 가정하지 않는다.'),
 'nest': ('M10', '군락 단위의 후보·동선 비용', '시간당 후보 = 유효 후보 수 / (전투+이동+정리 시간)', '전투만 측정하면 군락 이동·인벤토리 부담을 누락한다.', '군락별 실제 후보와 리셋을 먼저 측정하고 경로별 편차를 비교한다.', '리셋 주기 미확인을 무한 반복 가능으로 바꾸지 않는다.'),
 'weekly_rogue': ('M11', '무료 달성과 유료 수령의 분리', '유료 효율ᵣ = E[보상ᵣ|검은 꽃 수령]/60; 무료 점수 보상은 별도 계정', '한 번의 전투에 연관돼도 소비 행동력과 무료 목표 보상은 분모가 다르다.', '검은 꽃과 무음구역의 재료별 효율을 같은 단계에서 비교하며 ±5%는 검증할 제안 기준으로 둔다.', '모든 Cycle 보상을 동시에 수령하는 것으로 합산하지 않는다.'),
 'tutorial': ('M09', '공명자별 1회 보상', '지급 가능 = 해금 ∧ 완료 ∧ 미수령; 보상키 = 계정+공명자+튜토리얼 버전', '이름이 같아도 원본 ID가 다를 수 있으므로 실제 수령 키를 확인한다.', '한 번 학습한 보상이 중복 진입으로 반복 지급되지 않게 한다.', '65개 가이드 행을 서로 다른 공명자 65명으로 단정하지 않는다.'),
 'training': ('M09', '반복 학습과 최초 지급', '반복 연습 횟수 ≥ 0; 최초 보상 횟수 ≤ 1 (수령키별)', '학습은 재시도 가능하게, 최초 지급은 중복 방지하도록 분리한다.', '기술 확인과 성공 피드백을 중심으로 설계하고 반복 재화 파밍으로 전환하지 않는다.', '재입장 때 수령 플래그가 초기화되지 않아야 한다.'),
 'daily': ('M07', '활동도 달성 보상 곡선', 'B(a) = Σ rᵢI(a≥tᵢ); t = 20,40,60,80,100; 별의 소리 합계 60', '하루 여러 행동을 통해 같은 누적 목표를 달성하게 한다.', '60개 예산을 유지하고 중복 수령·리셋 경계를 확인한다.', '주간 목표와 일일 리셋을 혼합해 잔여 횟수를 계산하지 않는다.'),
 'double_reward': ('M12', '횟수 제한 배수 이벤트', '보상 묶음 수 = n + min(n,k)(m−1); n=4,k=3,m=2 → 7', '추가 횟수만 배수를 적용하며 기본 수령을 다시 더하지 않는다.', '3회·2배 프로필을 유지하고 잔여 배수 횟수와 유효 대상을 표시한다.', '활성 이벤트가 없을 때 배수를 기본 수급으로 계산하지 않는다.'),
 'rogue_archive': ('M13', '세션 내 성장과 영구 지급의 분리', '세션 잔액과 계정 잔액은 별도 원장; 영구 지급 = 미수령 조건을 만족한 Award 합', '전투 내부 통화를 영구 성장 재화처럼 환산하지 않는다.', '결말·도전·시즌 보상은 각 수령 키와 소멸 조건을 명시한다.', '과거 시즌 보상을 현재 반복 공급량으로 합치지 않는다.'),
 'event_framework': ('M14', '이벤트 생애주기와 지급 원장', '지급 = 활성기간 ∧ 참여자격 ∧ 완료조건 ∧ 미수령; 계정 총지급 ≤ 설계 예산', '등록 여부와 현재 활성 여부를 분리하고 종료 후 미수령 처리를 정의한다.', '기본 참여·숙련·수집·반복의 예산과 수령 조건을 각각 작성한다.', 'Activity 392개는 등록부이며 활성 이벤트 392개를 뜻하지 않는다.'),
}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Doc(components.Doc):
    def __init__(self, title, path, root, kind):
        self.title, self.path, self.root = title, Path(path), Path(root)
        self.html = ['<header><p class="meta">WUTHERING WAVES / 명조 · ' + html.escape(kind) + ' · 2026-11-18</p><h1>' + html.escape(title) + '</h1></header>']
        self.md = ['# ' + title + '\n', '문서 구분: ' + kind + ' · 2026-11-18 · 설치본 3.8.0\n']
        if self.path != self.root / 'index.html':
            self.p(Link('명조 문서 모음', os.path.relpath(self.root / 'index.html', self.path.parent)))

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prefix = os.path.relpath(self.root, self.path.parent).replace(os.sep, '/')
        text = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(self.title) + '</title><link rel="stylesheet" href="' + prefix + '/style.css"></head><body><main>' + ''.join(self.html) + '<footer>명조 설치본의 확인값, 공식 공개 확률, 과거 실측과 설계 제안을 구분합니다. 운영 서버에 적용한 변경은 없습니다.</footer></main><script src="' + prefix + '/filter.js"></script></body></html>'
        self.path.write_text(text, encoding='utf-8')
        self.path.with_suffix('.md').write_text('\n'.join(self.md), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--study', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    old, run, root = args.baseline.resolve(), args.study.resolve(), args.out.resolve()
    if root.exists():
        ap.error('Choose a new output directory')
    base = old.parent.parent
    sources = base / '외부자료/20261118'
    evidence = load(old / '콘텐츠_근거.json')
    definitions = load(old / '기획_정의.json')['plans']
    plans = {p['id']: p for p in definitions}
    farm = load(old / '파밍계산/결과.json')
    farm_input = load(old / '파밍_입력.json')
    study = load(run / '민감도_계산/결과.json')
    empirical = load(sources / '공개_보상요약.json')
    official = load(sources / '공식_부옵션확률.json')
    changes = load(old / '보고서/변경안_1.json')
    if farm['input_sha256'] != sha(old / '파밍_입력.json') or study['input_sha256'] != sha(run / '민감도_입력.json'):
        raise ValueError('Input/output hash mismatch')
    if study['study_script_sha256'] != sha(Path(__file__).with_name('명조_검토계산.py')):
        raise ValueError('Study code changed')
    for p, digest in {**evidence['source_files'], **farm_input['source_files']}.items():
        if sha(p) != digest:
            raise ValueError('Evidence changed: ' + p)
    rows_by_id = {s['id']: s for s in farm['echo_scenarios']}
    arms = {s['id']: s for s in study['arms']}
    for key in ['mean', 'p50', 'p90']:
        if not math.isclose(arms['t20']['days'][key], rows_by_id['crit_10']['metrics']['waveplate_equivalent_days'][key], abs_tol=1e-10):
            raise ValueError('Study baseline does not reproduce previous result')
    selected = min((s for s in study['arms'] if s['draft_feasible']), key=lambda s: s['tuners'])
    if selected['tuners'] != 24:
        raise ValueError('Revisit proposal: the comparison does not support the existing 24-tuner design')
    root.mkdir(parents=True)
    (root / 'style.css').write_text(components.STYLE + '\n.formula{padding:15px 20px;background:#f0f5fa;border-left:4px solid #426c93;overflow:auto;font-family:Consolas,monospace}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}.card{padding:23px;border:1px solid #d9e3e7;border-radius:8px}.card a{font-size:1.4rem;font-weight:700} nav{position:sticky;top:0;background:white;padding:12px 0;border-bottom:1px solid #d9e3e7;z-index:2}nav a{margin-right:20px}\n', encoding='utf-8')
    (root / 'filter.js').write_text(components.SCRIPT, encoding='utf-8')
    counts = Counter(e['category'] for e in evidence['catalog'])
    summaries = {(s['content'], s['group']): s for s in empirical['summaries']}

    def link(path, doc, text):
        return Link(text, os.path.relpath(path, doc.path.parent))

    def formula(doc, text):
        doc.html.append('<div class="formula">' + html.escape(text) + '</div>')
        doc.md.append('\n```text\n' + text + '\n```\n')

    def sources_block(doc, category=None):
        doc.heading('근거와 연결 문서')
        if category:
            doc.bullets([link(root / folder / (category + '.html'), doc, folder + ' · ' + plans[category]['title']) for folder in ['기획서', '분석서', '제안서'] if doc.path != root / folder / (category + '.html')])
        doc.bullets([link(root / '분석서/00_데이터와_방법.html', doc, '출처·버전·가정·계산 방법'), Link('공식 확률 공시 원문', components.OFFICIAL), Link('공개 실측 원본 시트', components.EMPIRICAL), link(old / '콘텐츠_근거.json', doc, '설치본 연결 근거와 원본 해시')])

    def scope(doc):
        doc.p('현재 서버의 활성 상태와 실제 유저 효과를 확인한 문서는 아니다. 설치본 3.8.0, 공식 공시, 2.0~2.5 및 일부 버전 미기재 실측을 사용했다. 변경값은 설계 제안이다.', callout=True)

    def empirical_table(doc, category=None):
        metric_names = {'exp': 'EXP', 'equivalent_green': '녹색 환산', 'material': '전용 재료'}
        rows = []
        for cat, group, field in [('tacet', 8, 'exp'), ('forgery', 80, 'equivalent_green'), ('forgery', 90, 'equivalent_green'), ('boss', 8, 'material'), ('weekly', 8, 'material'), ('role_exp', 8, 'exp'), ('weapon_exp', 8, 'exp')]:
            if category and cat != category:
                continue
            s = summaries[(cat, group)]; stat = s['metrics'][field]; ci = stat['normal_mean_ci95']
            rows.append([plans[cat]['title'], ('Lv' if cat == 'forgery' else '솔라리스 ') + str(group), s['n'], n(stat['mean']) + ' ' + metric_names[field], n(stat['sample_sd']), ' ~ '.join(n(v) for v in ci) if ci else '미산출', ', '.join(s['patch_counts']), s['distinct_contributors']])
        if rows:
            doc.table(['콘텐츠', '조건', '표본', '평균', '표본 표준편차', '평균 95% 구간', '관측 버전', '참여자'], rows)
            doc.p('이 구간은 관측을 독립 표본으로 보는 정규 근사다. 제보자 군집·시트 필터·버전 편향을 반영하지 않으므로 현행 서버값의 보장 구간으로 해석하지 않는다.')

    def scenario_table(doc):
        doc.table(['조건', '후보당 성공률', '평균 환산일', 'p50', 'p90', '평균 후보수(정확값)'], [[s['name'], n(s['exact_per_kept_echo']['success_probability_per_candidate'] * 100, 4) + '%', n(s['metrics']['waveplate_equivalent_days']['mean']), n(s['metrics']['waveplate_equivalent_days']['p50']), n(s['metrics']['waveplate_equivalent_days']['p90']), n(s['exact_per_kept_echo']['expected_candidates'])] for s in farm['echo_scenarios'] if s['keep'] == 1 and s['tuners_per_claim'] == 20])

    def study_table(doc):
        doc.table(['대안', '평균 환산일', '표본 p90', '기준 대비 평균 차이 95% 구간', '240 행동력당 튜너', '제안 조건 충족 (표본)'], [[s['name'], n(s['days']['mean'], 3), n(s['days']['p90'], 3), ' ~ '.join(n(v, 3) for v in s['paired_difference_days']['mc_ci95']), s['tuner_supply_per_240_waveplates'], '충족' if s['draft_feasible'] else '미충족'] for s in study['arms']])

    def profile_summaries(doc, cat, entry=None):
        def add(p, label):
            def body():
                if p.get('budget'):
                    doc.p('설정 최대 합계: ' + items_text(p['budget']))
                doc.table(['조건', 'Drop ID', '설치본 설정 미리보기'], [[s.get('condition', s.get('target', s.get('level', ''))), s['drop_id'], items_text(s['items'])] for s in p['steps']])
            doc.details(label, body)
        ps = evidence['profiles']
        if cat == 'tower':
            for p in ps['tower']:
                add(p, f"프로필 {p['profile_id']} · 난이도 {p['difficulty']} · 보상군 {p['reward_group']}")
        if cat == 'matrix':
            for p in ps['matrix']:
                if p['cycle_id'] == 9:
                    add(p, 'Cycle 9 / Level ' + str(p['level_id']))
        if cat == 'whimpering':
            for p in ps['whimpering']:
                if p['season'] in [0, 25]:
                    add(p, f"Season {p['season']} · {'추가' if p['endless'] else '일반'}")
        if cat == 'hologram':
            for p in ps['hologram']:
                if entry is None or p['entrance_id'] in entry.get('hologram_profiles', []):
                    add(p, p['name'] + ' / ' + str(p['entrance_id']))
        if cat == 'daily':
            add(ps['daily'], '일일 활동도 보상')
        if cat == 'weekly_rogue':
            doc.table(['예시 주기', '점수', 'Exchange ID', '설정 미리보기'], [[p['cycle_id'], p['score'], p['exchange_id'], items_text(p['stage8_items'])] for p in ps[cat]['point_rewards'] if p['cycle_id'] == 2101])
            doc.p('예시 2101의 별의 소리 합계는 100이다. 현재 활성 주기나 3801~3806의 실제 적용 보상으로 일반화하지 않는다.')

    for p in definitions:
        cat, title = p['id'], p['title']
        mid, model_title, equation, meaning, design_reason, edge = MODELS[cat]
        entries = [e for e in evidence['catalog'] if e['category'] == cat]
        # The planning specification states purpose, selected rule and implementation contract.
        doc = Doc(title + ' · 보상 설계 기획서', root / '기획서' / (cat + '.html'), root, '기획서 / 제안 상세 설계')
        doc.p(p['purpose'], callout=True)
        doc.table(['설계 항목', '내용'], [('기획 목표', design_reason), ('대상', p['audience']), ('적용 범위', f"가이드 {len(entries)}개 · {title}"), ('문서 상태', '구현 검토용 설계안. 서버 운영값 변경 미적용'), ('판단 근거', mid + ' · ' + model_title)])
        doc.heading('플레이 흐름과 보상 의도'); doc.bullets([f'{i}. {x}' for i, x in enumerate(p['loop'], 1)])
        doc.p('각 보상은 다음 성장 행동으로 이어져야 한다. 아래 규칙은 지급량, 소모, 반복 제한을 함께 정의하며 효과 평가는 연결 분석서의 조건에 한정한다.')
        doc.heading('보상 규칙과 파라미터')
        doc.table(['규칙', '설계값 / 처리', '의도'], [[c[0], c[2], c[3]] for c in p['changes']])
        doc.heading('계산 가능한 설계 모델'); formula(doc, equation); doc.p(meaning)
        if cat == 'tacet':
            doc.table(['입력', '설계값', '근거 구분'], [('행동력', '60/회', '설치본 소비 연결'), ('튜너', '24개/회', '이번 제안'), ('EXP', '기존 분포 유지', '과거 실측 평균 24,154.98 / 현행 재확인 필요'), ('부옵션', '13종 동일 확률·기존 종류 제외', '공식 공시'), ('레벨업/튜닝', '+5마다 비용 납부 후 1슬롯 공개', '설치본 비용'), ('보상 입력', '같은 회차 EXP·코인 묶음 보존', '관측 관계 보존')])
            doc.bullets(['서버 수령 시 적용 단계와 보상 버전을 확정하고 행동력 60과 지급을 하나의 수령 거래로 기록한다.', '8단계 튜너 항목을 변경하고 낮은 단계·이벤트 배수·주간 무료 보상을 암묵적으로 바꾸지 않는다.', '선별 기준은 이용자가 고른 옵션 목표다. 자동 폐기나 자동 자원 소비를 강제하는 기능을 제안한 것이 아니다.'])
        doc.heading('상태·예외·수령 계약')
        doc.table(['상태', '처리', '검증'], [('미해금', '해금 조건과 목표 재료를 표시', '입장 가능 여부를 서버 응답과 대조'), ('도전/조건 달성', '수령 자격·공유 잔여 횟수·비용 확인', '충족하지 못하면 지급 거래 생성 안 함'), ('수령 확정', 'claim_id로 비용 차감과 실제 보상 기록', '같은 요청 재전송 시 중복 지급 없음'), ('재접속/리셋', '기존 원장과 주기 ID 기준으로 복원', '클라이언트 화면 새로고침으로 횟수 초기화 안 됨')])
        doc.p('위 원장은 구현을 위한 제안 계약이며 명조 서버의 실제 내부 스키마를 확보했다는 뜻이 아니다.')
        doc.heading('완료 기준'); doc.table(['지표', '산식', '구분', '제안 판정'], p['kpis']); doc.bullets(p['checks'] + [edge])
        doc.p('현행 로그가 없는 효과 항목은 달성 여부 미확인으로 둔다. 제안 목표를 실제 이용자 성과로 표시하지 않는다.')
        doc.heading('적용 대상 목록'); doc.table(['가이드 ID', '이름', '지역', '행동력'], [[e['id'], link(root / '분석서/개별콘텐츠' / (str(e['id']) + '.html'), doc, e['name']), e['region'], n(e['waveplate_cost'])] for e in entries])
        sources_block(doc, cat); doc.write()

        # The analysis document contains present evidence and model interpretation only.
        doc = Doc(title + ' · 현황 분석서', root / '분석서' / (cat + '.html'), root, '분석서 / 확인값과 해석')
        scope(doc); doc.heading('확인한 구조와 해석'); doc.bullets(p['analysis'])
        empirical_table(doc, cat); profile_summaries(doc, cat)
        doc.heading(mid + ' · ' + model_title); formula(doc, equation); doc.p(meaning); doc.p('해석 한계: ' + edge)
        if cat == 'tacet':
            scenario_table(doc)
            doc.p('표의 환산일은 행동력/240이다. 유효 후보 확보 시간·전투 시간·해금·다른 소비는 포함하지 않았다.')
        if cat == 'shell':
            doc.p('84,000 코인은 작성자 고정 기재값이다. 개별 관측이 아니므로 표준편차나 평균 신뢰구간을 임의로 부여하지 않는다.')
        doc.heading('현재 연결된 대상'); doc.table(['ID', '대상', '지역', '행동력'], [[e['id'], link(root / '분석서/개별콘텐츠' / (str(e['id']) + '.html'), doc, e['name']), e['region'], n(e['waveplate_cost'])] for e in entries])
        doc.p('행동력 미확인은 무료 판정이 아니며 등록된 항목 수는 현재 개방된 콘텐츠 수와 다를 수 있다.')
        sources_block(doc, cat); doc.write()

        # The proposal document carries alternatives, decision and release guardrails.
        doc = Doc(title + ' · 개선 제안서', root / '제안서' / (cat + '.html'), root, '제안서 / 변경 결정과 검증')
        doc.p(design_reason, callout=True)
        doc.heading('문제 가설과 선택'); doc.bullets(p['analysis']); doc.p('위 데이터가 이용자의 실제 불편이나 이탈 원인을 입증하지는 않는다. 아래 안은 검증할 설계 가설이다.')
        doc.table(['대상', '기준', '제안', '선택 이유'], p['changes'])
        specific = [r for r in changes['rows'] if r['category'] == cat]
        if cat == 'tacet':
            doc.heading('대안 비교와 채택 근거'); study_table(doc)
            doc.p('제안 목표: EXP는 유지하고, 240 행동력당 튜너 증가를 16개 이내로 제한하며, 같은 모델의 p90을 6 환산일 이내로 낮춘다. 이는 기획자가 설정한 검토 기준이며 사용자가 확정한 사업 목표가 아니다.')
            doc.p('검토한 5개 안 중 24개안이 이 조건을 충족하는 최소 증가안이다. 22개안은 p90 6.083일, 26개안은 일일 추가 튜너 24개로 각각 조건을 넘는다. EXP만 10% 높인 안의 p90은 6.583일로 그대로다. 따라서 24개를 추천하되 모든 가능한 설계 중 전역 최적이라고 주장하지 않는다.')
            doc.p('검토 기준 자체에 동의하지 않으면 22개와 26개의 선택도 달라질 수 있다. 실제 지급 최신성·후보 수급·초기 재고를 확인한 뒤 운영 목표를 확정한다.')
            doc.p('선택은 5,000회 표본 p90을 기준으로 했다. 24개안의 보수적인 모의 p90 구간은 5.333~6.083일로 6일을 걸치므로, 모집단 p90이 6일 이하임을 통계적으로 확정한 것은 아니다. 추가 모의 검증과 현행 실측이 남은 추천 초안이다.')
        else:
            doc.heading('대안과 제외 이유')
            doc.table(['대안', '장점', '한계 / 선택 이유'], [('현행 유지', '기존 공급 구조 유지', '현재 확인된 안내·분배 문제 가설을 해결하는 효과는 제한적'), ('모든 보상 일괄 상향', '즉각적인 수급 증가', '부족하지 않은 재화와 상위 단계까지 함께 늘어 비용 대비 효과를 분리하기 어려움'), ('이번 범위의 변경 또는 관측 우선', design_reason, '적용 범위를 좁혀 지표와 지급 영향부터 확인')])
        if specific:
            doc.heading('설정값 전후와 예산 검사')
            doc.table(['범위', '조건', 'Drop ID', '기준', '제안'], [[r['scope'], r['condition'], r['drop_id'], r['before'], r['after']] for r in specific])
            doc.p('범위별 최대 보상 합계는 보존했다. 실제 총 지급량 보존을 뜻하지는 않는다. 낮은 구간의 달성자가 더 많으면 평균 지급량이 늘 수 있다. 공유 Drop ID를 직접 바꾸기 전에 해당 범위용 새 ID를 연결한다.')
        if cat == 'tower':
            formula(doc, 'ΔE[별의 소리] = 5Σ(q₁…q₈) − 10Σ(q₉…q₁₂)')
            doc.p('같은 36별 경로에서 q₁≥…≥q₁₂인 경우 계정당 기대 추가 지급은 0~40개다. 24별까지만 달성한 이용자는 600→640, 모두 달성한 이용자는 800으로 같다. 참여 계정이 U명이면 추가 지급 상한은 40U다.')
        if cat in ['matrix', 'whimpering', 'hologram']:
            formula(doc, 'ΔE[지급] = Σ (r제안ᵢ − r기준ᵢ)·qᵢ')
            doc.p('각 목표의 달성률 qᵢ를 같은 기간·대상 집단에서 측정해야 평균 지급 변화가 나온다. 최대 예산 합계만으로 인플레이션이 없다고 판정하지 않는다.')
        doc.heading('적용 순서와 검증 지표')
        doc.bullets(['1. 같은 버전의 현재 지급과 목표 달성률을 수집해 기준선을 확정한다.', '2. 해당 단계·콘텐츠·시즌에만 새 설정을 연결하고 수령·차감·리셋을 사전 검증한다.', '3. 버전·진행도·초기 재고를 맞춘 전후 집단 또는 실험 집단으로 비교한다. 표본 수와 기간은 사전 분산·트래픽을 보고 정한다.', '4. 중복 지급·한도 초과·비용 불일치는 즉시 복구한다. 목표 효과가 없거나 예상 외 재화가 병목이 되면 추가 확대를 중단하고 원인을 재검토한다.'])
        doc.table(['지표', '정의', '구분', '제안 기준'], p['kpis']); doc.p('현재 확보한 자료만으로 잔존율·매출·만족도 개선을 수치로 예측하지 않는다.')
        sources_block(doc, cat); doc.write()

    # Evidence sheets stay in the analysis collection and link to the distinct design documents.
    for e in evidence['catalog']:
        doc = Doc(e['name'] + ' · 개별 근거표', root / '분석서/개별콘텐츠' / (str(e['id']) + '.html'), root, '분석서 / 원본 연결')
        doc.table(['필드', '확인값'], [('가이드 ID', e['id']), ('유형 / 지역', e['category_name'] + ' / ' + e['region']), ('설명', e['description']), ('원본 테이블', e['source_table']), ('입구/던전 ID', e['dungeon_id']), ('LevelPlay ID', ', '.join(map(str, e['level_play_ids'])) or '해당 없음'), ('공명자 ID', e['role_id'] or '해당 없음'), ('행동력', n(e['waveplate_cost'])), ('해금 조건 / PreOpen ID', str(e['unlock_condition']) + ' / ' + str(e['preopen_id']))])
        doc.p('등록된 설정이며 현재 서버 활성 여부는 별도다. 행동력 미확인은 무료를 의미하지 않는다. 미리보기 수량 0은 가변 표시로 보존한다.', callout=True)
        doc.heading('비용 연결'); doc.table(['Exchange ID', '연결 방식', 'Instance ID'], [[v['id'], v['method'], v.get('instance_id', '')] for v in e['exchange_matches']])
        doc.heading('단계별 미리보기'); doc.table(['단계 키', 'Drop ID', '보상'], [[s['stage'], s['drop_id'], items_text(s['items'])] for s in e['preview_rows']])
        if e['calabash_preview_map']:
            doc.p('데이터 스테이션 참조 맵(별도 축): ' + json.dumps(e['calabash_preview_map'], ensure_ascii=False))
        if e['quotas']:
            doc.table(['교환 ID', 'MaxCount', 'SharedId'], [[q['exchange_id'], q['max_count'], q['shared']] for q in e['quotas']])
        if e['category'] == 'hologram':
            profile_summaries(doc, 'hologram', e)
        sources_block(doc, e['category']); doc.write()

    doc = Doc('명조 · 데이터와 분석 방법', root / '분석서/00_데이터와_방법.html', root, '분석서 / 방법')
    scope(doc)
    doc.heading('자료 계약')
    doc.table(['근거', '확보 범위', '쓸 수 있는 결론', '쓸 수 없는 결론'], [('설치본', '기존 96 + 추가 등록부 일치 173개 테이블; 가이드 209개', '비용·성장·보상 미리보기 연결', '현재 활성 상태·서버 지급 알고리즘 전체'), ('공식 공개 PDF', '13종 부옵션 종류와 수치 확률', '공시 조건의 일반 튜닝 계산', '모든 보정·재구성 시나리오의 동작'), ('공개 보상 관측', '채택 7,614회; 2.0~2.5 및 버전 미기재', '해당 과거 자료를 기준으로 한 재화 수급 모형', '3.8 서버 지급량과 모든 유저의 분포'), ('작성자 고정 참조', '튜너 20/회, 코인 84,000/40 등', '명시적 조건을 둔 계산', '개별 관측에서 검증한 확률 분포'), ('제안', '24튜너·앞 구간 재분배·UI 안내', '변경 전후 수학적 비교', '적용 완료·사용자 효과 입증')])
    doc.heading('재현 순서'); doc.bullets(['원본 파일 해시와 설치본 테이블 연결을 확인한다.', '공식 종류/수치 확률과 비용·환급을 입력한다.', '관측 보상 묶음을 보존해 복원 추출한다.', '동일 난수 시드의 기준안과 대안을 비교하고 평균·분위수·오차를 분리한다.', '서버 최신성·후보 공급·플레이 시간의 남은 가정을 기록한다.'])
    doc.heading('수량·시간·확률의 단위'); doc.table(['기호', '의미'], [('W', '소모 행동력; 일수와 다름'), ('D=W/240', '자연 회복 환산일'), ('C', '유효 세트·주옵션 후보 소모 개수'), ('p', '한 후보가 해당 정책에서 목표를 만족할 확률'), ('qᵢ', '보상 목표 i를 달성한 이용자 비율'), ('E[R]', '수령 1회의 평균 보상'), ('p90', '모의 결과의 90번째 백분위. 평균의 신뢰구간과 다름')])
    doc.heading('실제 반복 검증을 위한 로그'); doc.table(['영역', '필수 필드', '오류 방지'], [('보상', 'claim_id, 익명계정, 버전, 콘텐츠, 난이도, 최초/반복, 배수, 품목·수량, 행동력, 전후 잔액', '같은 수령의 전체 보상 묶음 보존'), ('튜닝', 'echo_id, 슬롯, 이전 종류, 새 종류·수치, 폐기 단계, 환급', '성공품만 수집하는 선택 편향 방지'), ('플레이', '시도·성공·포기, 전투/이동/정리 시간', '성공 전투만의 분당 효율 과대평가 방지'), ('구간 보상', '시즌, 프로필, 목표별 달성·수령 여부', '최대 예산과 실제 발행량 분리')])
    doc.bullets([link(old / '파밍_입력.json', doc, '기존 파밍 입력'), link(run / '민감도_입력.json', doc, '추가 대안 비교 입력'), link(run / '민감도_계산/결과.json', doc, '추가 계산 결과'), link(sources / '수집_명세.json', doc, '외부 자료 수집 명세'), Link('공식 확률 PDF', components.OFFICIAL), Link('공개 관측 원본', components.EMPIRICAL)])
    doc.write()

    doc = Doc('명조 · 에코 성장과 확률 모델', root / '분석서/01_확률과_성장모델.html', root, '분석서 / 수학 모델')
    doc.heading('1. 중복 없는 종류 추첨')
    formula(doc, 'P(필수 k종 포함) = C(13−k, 5−k) / C(13, 5)')
    doc.p('13종 중 5슬롯을 뽑을 때 필수 종류를 먼저 고정하고 나머지 슬롯을 고르는 경우의 수를 전체 경우의 수로 나눈다. 종류별 수치 제한이 없고 끝까지 5슬롯을 여는 조건이다.')
    doc.table(['목표', '확률', '후보 기대 개수'], [('쌍크리 2종', n(math.comb(11, 3) / math.comb(13, 5) * 100, 4) + '%', '7.8'), ('쌍크리 + 공격력% 3종', n(math.comb(10, 2) / math.comb(13, 5) * 100, 4) + '%', n(math.comb(13, 5) / math.comb(10, 2)))])
    doc.heading('2. 수치 제한과 선별 상태')
    formula(doc, 'q종류(최소값) = Σ 최소값 이상 수치의 공개 확률; 상태 = (미등장, 조건 충족, 수치 미달)')
    doc.p('각 슬롯에서는 아직 나오지 않은 종류만 선택한다. 필요한 종류가 수치 미달이면 다시 같은 종류를 뽑을 수 없으므로 해당 후보에서 목표 달성은 불가능하다. 공개 종류별 수치 분포는 사용하되 서로 다른 옵션 수치 사이의 미공개 상관관계는 모델링하지 않는다.')
    doc.table(['정책', '폐기 규칙', '자원·후보의 교환'], [('매번 +25', '5슬롯 완성 후 판정', '후보를 아끼지만 실패품에 많은 자원 투자'), ('+10 선별', '+10까지 유효 크리티컬이 없거나 목표 불가능 시 폐기', '후보를 더 사용하고 자원 소비를 줄임'), ('+15 선별', '+15까지 유효 크리티컬이 없거나 목표 불가능 시 폐기', '두 정책 사이의 절충')])
    doc.heading('3. 비용·환급과 정확 기대값')
    doc.table(['단계', '누적 EXP', '누적 코인', '누적 튜너', '폐기 EXP 환급', '폐기 튜너 환급'], [[c['level'], n(c['cumulative_exp']), n(c['total_coins']), c['tuners'], n(c['refunded_exp']), c['refunded_tuners']] for c in farm_input['checkpoints']])
    formula(doc, 'E[순비용/완성] = (Σ P(단계 도달)·추가 비용 − Σ P(단계 폐기)·환급) / p정책')
    doc.p('실패 후 같은 정책으로 독립 후보를 다시 평가하는 갱신 과정이다. 비용을 성공 확률로 나눌 때에는 중간 폐기·환급을 포함한 후보 1개당 기대 비용을 사용한다.')
    doc.table(['정책', '성공률', '후보 기대값', '순 EXP', '순 튜너', '코인'], [[s['name'], n(s['exact_per_kept_echo']['success_probability_per_candidate'] * 100, 4) + '%', n(s['exact_per_kept_echo']['expected_candidates']), n(s['exact_per_kept_echo']['expected_net_xp']), n(s['exact_per_kept_echo']['expected_net_tuners']), n(s['exact_per_kept_echo']['expected_coins'])] for s in farm['echo_scenarios'] if s['id'] in ['crit_full', 'crit_10', 'crit_15']])
    doc.heading('4. 비용을 수급으로 연결'); formula(doc, 'Bᵣ,t+1 = Bᵣ,t + 수령ᵣ + 환급ᵣ − 성장비용ᵣ; D = (60N무음 + 40N코인)/240')
    doc.p('EXP·튜너가 모자라면 무음구역을, 코인만 모자라면 코인 영역을 즉시 수령한다. 모든 잔액을 함께 추적하므로 평균 비용/평균 보상만으로 기간을 구하지 않는다. 이 순차 수령 정책은 최소 행동력 최적해를 뜻하지 않는다. EXP는 합산 자원으로 처리해 개별 재료 초과 투입은 제외했다.')
    scenario_table(doc); doc.bullets(farm['assumptions'] + farm['limitations']); sources_block(doc, 'tacet'); doc.write()

    doc = Doc('명조 · 공개 실측 통계 분석', root / '분석서/02_실측통계.html', root, '분석서 / 통계')
    doc.p('자료는 관측 당시의 보상 분포를 보여 준다. 시트 작성자의 채택 필터를 그대로 사용하므로 실제 전체 이용자를 무작위로 뽑은 표본이 아니다.', callout=True)
    empirical_table(doc)
    formula(doc, '평균 = Σ xᵢ/n; 표본분산 s² = Σ(xᵢ−평균)²/(n−1); 근사 평균 구간 = 평균 ± 1.96·s/√n')
    doc.p('n≥30에서 표시한 근사 구간도 정규 근사와 독립 표본 전제에 의존한다. 표본 수가 많아도 버전 편향이나 특정 제보자의 반복 관측 편향이 없어지는 것은 아니다.')
    doc.heading('관측 채택과 대표성'); doc.table(['영역', '채택 수', '제외 수', '필터'], [[x['content'], x['accepted_rows'], x['excluded_rows'], x['filter']] for x in empirical['filters']])
    dist = Counter(int(x['exp']) for x in farm_input['tacet_rows'])
    doc.heading('무음구역 8단계의 관측 분포'); doc.table(['EXP/회', '관측 횟수', '관측 비율'], [[n(value), count, n(count / sum(dist.values()) * 100) + '%'] for value, count in sorted(dist.items())])
    doc.p('튜너 20개와 코인 영역 84,000은 작성자의 고정 참조 셀이다. 개별 관측 분포를 확보한 것처럼 n이나 분산을 만들지 않는다. 무기 EXP 8단계는 34회이며 패치 구성도 다르므로 하위 단계보다 평균이 낮다는 이유만으로 실제 보상 역전을 단정하지 않는다.')
    doc.heading('목표 재료의 정지시간')
    formula(doc, 'N = min{n: Σ Xᵢ ≥ 목표}; E[N] ≠ ceil(목표/E[X])인 경우가 일반적')
    doc.table(['목표', '평균 횟수', 'p50', 'p90', '평균 행동력 환산일'], [[s['name'], n(s['claims']['mean']), s['claims']['p50'], s['claims']['p90'], n(s['waveplate_equivalent_days']['mean'])] for s in farm['material_scenarios']])
    doc.p('각 재료를 단독으로 수급하는 계산이다. 캐릭터·무기·에코 전체 성장 기간으로 합치면 부수 보상과 경쟁 소비를 중복 계산할 수 있다. 주간 재료 12개는 4회 수령이므로 2개 수령 주기에 걸친다.')
    sources_block(doc); doc.write()

    doc = Doc('명조 · 대안 민감도와 오차 분석', root / '분석서/03_대안_민감도.html', root, '분석서 / 대안 계산')
    doc.p('같은 5,000개의 튜닝·지급 난수 시드를 대안마다 재사용했다. 결과의 차이는 같은 후보열을 경험한 가상 계정끼리 비교한다.', callout=True)
    study_table(doc)
    formula(doc, 'dᵢ = D대안,ᵢ − D기준,ᵢ; 평균 차이 구간 = d평균 ± 1.96·s_d/√n')
    doc.p('표의 구간은 이 모델의 몬테카를로 평균 오차만 나타낸다. 과거 보상 표본의 불확실성이나 실제 이용자의 행동 차이는 포함하지 않는다.')
    doc.table(['대안', 'p90', 'p90 모의 오차 95% 보수 구간'], [[s['name'], n(s['days']['p90'], 3), ' ~ '.join(n(x, 3) for x in s['p90_interval']['p90_mc_ci95'])] for s in study['arms']])
    formula(doc, 'ε = √(ln(2/α)/(2n)); p90 구간 = [표본 Q(0.9−ε), 표본 Q(0.9+ε)]')
    doc.p('이는 경험분포의 DKW 경계를 역으로 적용한 보수적 구간이다. 표본 수 5,000, α=0.05이며 관측의 독립성을 전제한다. 해당 구간이 좁아도 모델 가정이 맞다는 뜻은 아니다.')
    doc.p('24개안은 표본 p90 기준으로 제안 목표를 충족하지만 그 모의 구간 상한은 6.083일이다. 따라서 6일 이하라는 모집단 판정까지 통과했다고 표현하지 않는다. 22개안도 경계 주변이므로 표본 결과만으로 두 안의 실제 서비스 적합성을 단정하지 않는다.')
    doc.heading('후보가 부족하면 선별 선택이 바뀐다')
    full, ten, fifteen = [rows_by_id[k] for k in ['crit_full', 'crit_10', 'crit_15']]
    def breakeven(a, b):
        return (b['metrics']['waveplates']['mean'] - a['metrics']['waveplates']['mean']) / (a['exact_per_kept_echo']['expected_candidates'] - b['exact_per_kept_echo']['expected_candidates'])
    formula(doc, '검토용 부담 점수 J = E[행동력] + λ·E[후보 개수]')
    doc.table(['비교', '후보 비용 λ의 교차점', '의미'], [('+10 선별 vs +15 선별', n(breakeven(ten, fifteen)), '추가 후보 1개의 환산 부담이 이 값보다 높으면 +15가 유리해질 수 있음'), ('+10 선별 vs 매번 +25', n(breakeven(ten, full)), '후보가 매우 귀하면 +25를 끝까지 여는 가치가 커짐')])
    doc.p('λ는 행동력과 비교하기 위한 검토용 환산 가중치다. 게임에서 후보 획득에 실제로 해당 행동력을 낸다는 뜻이 아니다. 후보 수의 정확 기대값과 행동력의 모의 평균을 사용한 조건부 교차점이며 실제 플레이 시간 측정으로 보정해야 한다.')
    doc.bullets([link(run / '민감도_입력.json', doc, '민감도 입력과 제안 목표'), link(run / '민감도_계산/결과.json', doc, '정확한 계산 결과'), link(run / '민감도_계산/쌍체_시행.csv', doc, '25,000개 대안별 시행 기록')]); sources_block(doc, 'tacet'); doc.write()

    doc = Doc('명조 · 보상 곡선과 실제 지급량', root / '분석서/04_보상곡선과_발행량.html', root, '분석서 / 경제 모델')
    formula(doc, '최대 예산 Bmax = Σ rᵢ; 1계정 기대 지급 E[B] = Σ rᵢqᵢ; 전체 기대 지급 = 참여계정 수 × E[B]')
    doc.p('총량 보존은 모든 목표를 완료한 계정의 최대 수령량을 보존한다. 이용자가 실제로 완료하는 구간 비중이 다르면 평균 지급량은 바뀐다. 따라서 앞 구간 보상 확대를 무조건 재화 인플레이션이 없는 변경으로 설명할 수 없다.', callout=True)
    doc.table(['경우', '24별까지', '36별까지', '계정당 차이'], [('현재', '600', '800', '—'), ('제안', '640', '800', '24별 계정 +40, 완주 계정 0')])
    formula(doc, '탑 ΔE = 5Σ(q₁…q₈) − 10Σ(q₉…q₁₂), 같은 순차 목표에서 0 ≤ ΔE ≤ 40')
    doc.p('가령 모든 참여자가 정확히 24별에 머문다는 가상 경계 사례에서는 평균 +40이다. 이는 실제 분포의 관측 결과가 아니다. 시즌별 qᵢ와 참여 계정 수를 받아야 실제 추가 발행량을 산출할 수 있다.')
    doc.heading('검증된 최대 예산 보존'); doc.table(['유형', '적용 범위', '기준', '제안', '검사'], [[c['category'], c['scope'], c['before'], c['after'], '일치'] for c in changes['budget_checks']])
    doc.p('동일한 Drop ID가 여러 시즌에서 재사용될 수 있다. 계정 수와 목표 달성률을 확인하는 것과 별개로 적용 범위의 ID를 분리해야 한다.'); sources_block(doc); doc.write()

    doc = Doc('명조 · 이벤트 등록부', root / '분석서/이벤트_등록부.html', root, '분석서 / 등록부')
    doc.p('392개는 설치본 Activity 등록 행이며 현재 활성 이벤트 수가 아니다. 전체 이벤트의 세부 지급 테이블을 모두 해석했다는 뜻도 아니다.', callout=True)
    doc.filters('events'); doc.table(['ID', '이름', 'Type', '숨김', '미리보기 ID', '보상 미리보기'], [[e['id'], e['name'], e['type'], e['hidden'], e['preview_id'], items_text(e['preview_items'])] for e in evidence['activities']], table_id='events'); doc.write()

    doc = Doc('명조 · 서버와 클라이언트의 보상 연결', root / '분석서/서버_클라이언트_연결.html', root, '분석서 / 데이터 경계')
    doc.p('서버가 추첨 결과를 보내면서 서버용 테이블로 보상량과 가중치를 관리하는 구조는 가능하다. 설치본에 서버 테이블 전체가 들어 있다는 뜻은 아니다. 이번에 확보한 것은 클라이언트 테이블, 결과 수신 코드, 공식 확률과 관측 자료다.', callout=True)
    doc.table(['경로', '확인 내용'], [('비용', 'InstanceDungeon.RewardId → ExchangeReward.Cost; 입구 PowerCostShow는 실제 소비와 다른 값이 있어 사용하지 않음'), ('보상 결과', '22096 → ItemHintController → OnItemRewardNotify → ItemRewardController의 L8n/m9n/b9n'), ('튜닝 결과', 'RequestPhantomIdentify 26204 → xPs 적용 → PhantomDataBase.UpdateData에서 Wws 수신'), ('미확보', '서버 최종 보상 풀·가중치·보정 구현·현재 활성 설정')])
    sources_block(doc); doc.write()

    doc = Doc('명조 · 보상·성장 통합 기획서', root / '기획서/00_통합기획서.html', root, '기획서 / 통합 설계')
    doc.p('성장 재료를 지급하는 콘텐츠와 성장 결과를 시험하는 콘텐츠의 역할을 나누고, 이용자가 다음 목표에 필요한 비용을 예측할 수 있게 한다.', callout=True)
    doc.heading('설계 목적과 성공 조건')
    doc.table(['설계 의도', '규칙으로 표현한 것', '측정할 결과'], [('중간 선별의 튜너 병목 완화', '8단계 튜너 24개, EXP·비용·확률 유지', '조건부 평균·p90, 튜너/EXP/코인 부족 상태'), ('도전 진입 단계의 보상 접근성', '정해진 최대 예산 안에서 초기 구간 분배 확대', '목표별 달성률·수령률·실제 발행량'), ('공유 성장 자원의 예측 가능성', '재고·예약 비용·주간 공유 잔여 횟수 표시', '잘못된 재료 수령·소모·목표 지연 감소 여부'), ('근거에 비례하는 변경', '표본·최신성이 부족하면 관측 우선', '같은 버전/조건의 추가 데이터 확보')])
    doc.heading('공통 성장 흐름'); doc.bullets(['목표 선택 → 재고·해금·잔여 쿼터 확인 → 재료 콘텐츠 선택 → 수령 → 성장 → 도전 콘텐츠에서 성과 확인.', '반복 수급은 재료 소비를, 주기·최초 보상은 진행과 숙련 성과를 담당한다.', '계정 전체의 수입·소모를 연결하되 모든 재화를 한 가지 임의 가치로 합치지 않는다.'])
    doc.heading('수학 모델과 설계 규칙 대응'); doc.table(['유형', '모델', '규칙의 근거'], [[link(root / '기획서' / (p['id'] + '.html'), doc, p['title']), MODELS[p['id']][0] + ' · ' + MODELS[p['id']][1], MODELS[p['id']][4]] for p in definitions])
    doc.heading('무음구역의 상세 의도와 계산 예')
    doc.p('쌍크리 1개를 만들 때 매번 +25까지 투자하면 후보 기대값은 7.8개, 순 튜너는 288개다. +10 선별은 후보 기대값 11.14개, 순 튜너 240개다. 따라서 중간 선별은 후보를 더 쓰는 대신 자원 비용을 낮추며, 후보가 부족한 이용자에게 항상 같은 정책을 강요할 수 없다.')
    doc.p('재료 공급안은 그 정책 차이를 유지한 채 병목을 줄이는 안이다. 24튜너안의 근거는 같은 조건의 대안 비교에서 확인하고, 실제 적용 시 목표 세트·주옵션 후보 생산성을 함께 측정한다.')
    doc.heading('공통 검수 조건'); doc.bullets(['동일 수령 요청의 재전송으로 보상이나 비용이 중복 처리되지 않는다.', '처음/반복/주간/이벤트 배수의 수령 키가 서로 겹치지 않는다.', '주기 최대 예산을 맞추는 검사와 실제 지급량 변화를 보는 검사를 별도로 수행한다.', '현행값·공식 확률·과거 실측·기획자 제안을 표와 로그에서 구분한다.', '가상 예시게임의 성장 모델은 명조 수치에 포함하지 않는다.'])
    doc.p(link(root / '분석서/01_확률과_성장모델.html', doc, '계산식과 원본 수치')); doc.p(link(root / '제안서/00_개선안_의사결정.html', doc, '대안 선택과 검증 계획')); doc.write()

    doc = Doc('명조 · 개선안 의사결정 제안서', root / '제안서/00_개선안_의사결정.html', root, '제안서 / 통합 판단')
    doc.p('우선 추천은 무음구역의 튜너 병목 완화와 공유 비용·목표 안내 개선이다. 주기 보상 재분배는 실제 발행량 증가를 추정한 뒤 적용 범위를 결정한다.', callout=True)
    doc.table(['순서', '제안', '계산 근거', '아직 검증할 것'], [('1', '무음구역 8단계 튜너 24개', '동일 조건 p90 6.583→5.583, 최대 일일 튜너 80→96', '현재 지급 분포·후보 공급·초기 재고·코인 병목'), ('1', '목표 부족 재화·주간 공유 쿼터 안내', '재화 보존·주기 제약 모델', '잘못된 수령과 목표 지연 감소 효과'), ('2', '주기/최초 보상 앞 구간 재분배', '27개 최대 예산 보존 검사', '목표 달성률에 따른 실제 통화 발행량 증가'), ('2', '응소 Lv80 동일 계열 녹색 +3', '평균 환산 34.90→37.90', '3.8 현행값, 단계별 체류와 상위 단계 진입 효과'), ('관측', 'EXP·보스·악몽·군락 등', '현재 자료만으로 일괄 증액 근거 부족', '버전별 유효 후보·시간·실제 수령 분포')])
    doc.heading('무음구역의 대안 선택'); study_table(doc)
    doc.p('EXP 유지·추가 튜너 최대 16개/240 행동력·p90 6환산일 이내라는 기획자 제안 목표에서는 검토한 대안 중 24개를 선택한다. 운영 목표가 달라지면 선택도 다시 계산한다.')
    doc.p('이 선택은 표본 p90 기준의 추천이다. 24개안의 모의 p90 구간 5.333~6.083일은 목표 경계를 걸친다. 모집단이나 실제 서비스에서 목표 달성을 확정한 결과가 아니며, 추가 검증을 적용 조건으로 둔다.')
    doc.heading('적용 판단에 필요한 증거'); doc.bullets(['설치본 3.8과 현재 서버 지급의 차이가 없는지 실제 수령으로 확인한다.', '보상 변화가 목표 기간을 줄이는지와 코인·후보 병목을 새로 만드는지를 함께 본다.', '주기 최대 예산을 지켜도 평균 발행량이 늘 수 있으므로 목표별 달성률로 추가 공급을 계산한다.', '잔존율·만족도·매출 효과는 이 모델로 검증되지 않았다. 해당 효과를 채택 근거에 넣으려면 별도 이용자 실험이 필요하다.'])
    doc.heading('세부 제안'); doc.table(['콘텐츠', '선택 방향'], [[link(root / '제안서' / (p['id'] + '.html'), doc, p['title']), MODELS[p['id']][4]] for p in definitions]); doc.write()

    # Separate collection indexes.
    for folder, subtitle, anchor in [('기획서', '목적·흐름·규칙·파라미터·완료 기준', '00_통합기획서.html'), ('분석서', '출처·계산식·통계·현황·한계', '00_데이터와_방법.html'), ('제안서', '기준 대비 변경·대안 비교·채택 이유·검증 계획', '00_개선안_의사결정.html')]:
        doc = Doc('명조 · ' + folder + ' 모음', root / folder / 'index.html', root, folder + ' / 목차')
        doc.p(subtitle, callout=True); doc.p(Link('통합 문서부터 읽기', anchor))
        if folder == '분석서':
            doc.bullets([Link(title, name) for name, title in [('01_확률과_성장모델.html', '수학 모델: 확률·비용·환급'), ('02_실측통계.html', '통계: 실측·표본·평균 구간'), ('03_대안_민감도.html', '대안 비교·모의 오차·후보 비용'), ('04_보상곡선과_발행량.html', '보상 곡선·최대 예산·실제 발행량'), ('서버_클라이언트_연결.html', '서버와 클라이언트 경계'), ('이벤트_등록부.html', '392개 이벤트 등록부')]])
        doc.table(['콘텐츠', '개별 가이드 수', '모델'], [[Link(p['title'], p['id'] + '.html'), counts.get(p['id'], 0), MODELS[p['id']][0] + ' · ' + MODELS[p['id']][1]] for p in definitions])
        if folder == '분석서':
            doc.heading('209개 개별 근거표'); doc.filters('entries', [(p['id'], p['title']) for p in definitions if counts.get(p['id'])]); doc.table(['ID', '대상', '유형', '지역'], [[e['id'], Link(e['name'], '개별콘텐츠/' + str(e['id']) + '.html'), e['category_name'], e['region']] for e in evidence['catalog']], table_id='entries', categories=[e['category'] for e in evidence['catalog']])
        doc.write()

    doc = Doc('명조 · 보상·성장 밸런스 문서', root / 'index.html', root, '문서 모음')
    doc.p('대상 게임: 명조(Wuthering Waves). 실제 설치본에서 추출한 자료와 공개 근거로 작성했습니다. 기획서·분석서·제안서를 목적별로 모았습니다.', callout=True)
    doc.html.append('<div class="cards">' + ''.join('<div class="card"><a href="' + folder + '/index.html">' + folder + '</a><p>' + desc + '</p></div>' for folder, desc in [('기획서', '무엇을 왜 어떻게 설계할 것인가'), ('분석서', '무슨 데이터와 계산이 판단을 뒷받침하는가'), ('제안서', '어떤 대안을 선택하고 어떻게 검증할 것인가')]) + '</div>')
    doc.md.append('\n' + '\n'.join('- [' + folder + ' 모음](<' + folder + '/index.md>)' for folder in ['기획서', '분석서', '제안서']) + '\n')
    doc.heading('권장 읽기 순서'); doc.bullets([Link('1. 통합 기획서 — 설계 목적과 규칙', '기획서/00_통합기획서.html'), Link('2. 수학 모델 — 확률·선별·환급', '분석서/01_확률과_성장모델.html'), Link('3. 통계와 대안 비교 — 오차·민감도', '분석서/03_대안_민감도.html'), Link('4. 통합 제안서 — 채택 이유와 검증 계획', '제안서/00_개선안_의사결정.html')])
    doc.heading('요청한 작성 기준과 대응 자료')
    doc.table(['작성 기준', '문서에서 확인할 내용'], [('수학적·통계적 근거를 갖춘 논리적 모델', Link('비복원 확률, 상태 전이, 비용 보존, 표본·오차', '분석서/01_확률과_성장모델.html')), ('복잡한 수치와 설계 의도를 명확하게 전달', Link('의도 → 규칙 → 파라미터 → 검수 기준', '기획서/00_통합기획서.html')), ('구체적인 개선 제안', Link('5개 대안의 같은 조건 비교와 선택 기준', '제안서/tacet.html'))])
    doc.heading('이전 화면의 예시게임 안내'); doc.p('「예시게임 / 성장던전」은 계산기 검증용 가상 모델이다. 명조 분석이 아니며 이 문서의 계산 입력에도 포함하지 않았다.')
    doc.heading('범위와 상태'); doc.p('20개 유형의 기획서·분석서·제안서와 209개 개별 근거표를 제공합니다. 392개 이벤트는 등록부 부록입니다. 실측은 과거 버전이며 후보 획득·실제 플레이 시간과 현재 서버 상태는 남은 검증 항목입니다.')
    doc.bullets([link(old / '보고서/명조_콘텐츠별_보상밸런스_기획서.html', doc, '이전 통합 문서(보존)'), link(run / '민감도_계산/결과.json', doc, '추가 비교 계산'), Link('문서 생성 명세', '문서_명세.json')]); doc.write()

    manifest = {'game': '명조', 'date': '2026-11-18', 'status': 'review_pending', 'selected_arm': selected['id'], 'counts': {'planning': len(definitions) + 1, 'analysis_category': len(definitions), 'analysis_method': 5, 'individual_evidence': len(evidence['catalog']), 'proposals': len(definitions) + 1, 'event_registrations': len(evidence['activities'])}, 'source_files': {str(p): sha(p) for p in [old / '콘텐츠_근거.json', old / '기획_정의.json', old / '파밍_입력.json', old / '파밍계산/결과.json', old / '보고서/변경안_1.json', sources / '공개_보상요약.json', sources / '공식_부옵션확률.json', run / '민감도_입력.json', run / '민감도_계산/결과.json', Path(__file__).resolve(), GENERATOR]}, 'files': {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}}
    components.save_json(root / '문서_명세.json', manifest)
    print(json.dumps({'out': str(root), 'counts': manifest['counts'], 'selected_arm': selected['id']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
