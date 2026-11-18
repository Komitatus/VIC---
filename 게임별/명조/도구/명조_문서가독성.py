#!/usr/bin/env python3
"""Reframe verified Wuwa documents around decisions, with technical evidence retained."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

from 명조_문서아이콘 import Node, Parser, node

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / '콘텐츠/명조/클라이언트분석'
EVIDENCE = BASE / '결과/20261118_콘텐츠기획'
CASE = ROOT / '개별보고서/명조_중부평원_무음구역/중부평원_무음구역_재화분석과_개선안.html'

# Problem, decision, rationale, concrete example, condition/risk.
BRIEFS = {
 'forgery': (
  '최고 난이도에 진입하기 전에도 무기와 스킬 재료는 필요하다. Lv80 구간의 재료 공급을 조금 늘려 성장 대기 부담을 줄이는 안이다.',
  'Lv80 보상에 같은 계열의 녹색 재료 3개를 더한다. Lv90 보상은 유지한다.',
  '낮은 등급 재료는 합성할 수 있으므로 희귀 재료의 확률을 바꾸지 않고도 확보량을 늘릴 수 있다. 서로 다른 계열의 재료는 합산하지 않는다.',
  '과거 실측을 녹색 재료 기준으로 환산하면 Lv80은 평균 34.90개다. 3개를 더하면 37.90개로 약 8.6% 증가한다. Lv90의 비교 기준은 51.00개다.',
  '현재 버전의 실제 지급량을 확인한 뒤 비교해야 한다. Lv80 보상을 늘린 결과 상위 단계에 진입할 이유가 약해지는지도 확인한다.'),
 'role_exp': (
  '경험치 재료를 충분히 모아도 코인이나 돌파 재료가 부족하면 공명자를 성장시킬 수 없다. 다음에 무엇을 모아야 하는지 함께 알려줄 필요가 있다.',
  '경험치 지급량은 우선 유지하고 목표 레벨까지 부족한 경험치와 다른 성장 재료를 함께 표시한다.',
  '경험치만 늘리면 부족한 재화가 코인이나 돌파 재료로 바뀔 수 있다. 먼저 성장에 필요한 재료를 한 화면에서 확인하게 한다.',
  '8단계의 과거 표본 평균은 회당 78,440 EXP다. 현재 경험치와 보유 재료를 먼저 차감한 부족량을 기준으로 다음 수령을 안내한다.',
  '이 수치는 과거 표본 평균이다. 실제 횟수 안내에는 현행 지급량과 이용자 재고가 필요하며, 안내 개선의 효과는 재료 초과 사용과 성장 보류 비율로 확인한다.'),
 'weapon_exp': (
  '무기 레벨업은 경험치, 코인, 돌파 재료가 함께 충족되어야 가능하다. 경험치만 보는 안내로는 다음 성장 행동을 판단하기 어렵다.',
  '지급량 변경은 보류하고 경험치, 코인, 돌파 재료의 부족량을 함께 보여준다.',
  '작은 표본의 평균 차이를 곧바로 난이도별 보상 문제로 판단하지 않는다. 같은 버전의 관측을 늘리면서 어떤 재료가 성장을 막는지 구분한다.',
  '8단계 경험치의 표본 평균은 79,058.82 EXP지만 관측은 34회다. 이 평균을 매회 확정 지급량으로 안내하면 안 된다.',
  '지급량을 조정하기 전 표본을 추가한다. 성장 목표가 같은 이용자끼리 코인 부족, 돌파 재료 부족, 경험치 부족을 나눠 비교한다.'),
 'shell': (
  '공명자, 무기, 에코가 같은 코인을 사용한다. 각 성장 목표를 따로 계획하면 같은 잔액을 여러 번 쓸 수 있는 것처럼 계산하기 쉽다.',
  '목표별로 필요한 코인을 합산하고 이미 예약한 비용과 자유롭게 쓸 수 있는 잔액을 나눠 보여준다.',
  '코인 공급을 늘리기 전에 여러 성장 목표가 충돌하는 지점을 보이게 한다. 이용자가 성장 순서를 정할 수 있게 하는 것이 목적이다.',
  '비교에 사용한 코인 시뮬레이션 참조값은 행동력 40당 84,000코인이다. 무음구역 방문이 줄면 그곳에서 부수적으로 얻던 코인도 줄 수 있다.',
  '84,000은 공개 시트의 참조값이다. 현행 지급을 확인하고, 튜너 개선안 적용 시 추가 코인 파밍이 얼마나 늘어나는지 함께 본다.'),
 'boss': (
  '공명자 돌파에는 지정된 전용 재료가 필요하다. 획득량뿐 아니라 목표 재료를 주는 강적을 정확히 선택하는 것이 중요하다.',
  '재료 지급량은 유지하고 현재 부족한 재료를 주는 강적을 우선 안내한다.',
  '과거 표본에서는 회당 지급 범위가 4~5개로 좁았다. 일괄 증액보다 잘못된 재료 수령을 줄이는 방향을 먼저 검토한다.',
  '46개를 모으는 과거 조건의 계산에서 p90은 11회다. 마지막 수령에서 필요량을 초과할 수 있으므로 46을 평균 지급량으로 나눈 값과 실제 횟수는 다를 수 있다.',
  '현재 버전과 보스별 지급을 확인한다. 재료를 모으는 횟수와 전투에 걸리는 시간은 별도 지표로 측정한다.'),
 'weekly': (
  '주간 도전은 여러 보스가 수령 횟수를 공유한다. 개별 보상만 보고 선택하면 필요한 재료를 받기 전에 주간 기회를 소진할 수 있다.',
  '주 3회의 공유 수령 제한을 유지하고 남은 횟수와 목표 재료까지 필요한 수령 주기를 함께 표시한다.',
  '이 콘텐츠의 성장 속도는 행동력뿐 아니라 주간 횟수로 제한된다. 두 제약을 나눠 알려줘야 계획을 세울 수 있다.',
  '회당 3개씩 필요한 재료 12개를 얻으려면 4회가 필요하다. 주 3회 제한이라면 두 수령 주기에 걸치지만, 시작 요일에 따라 실제 대기 일수는 달라진다.',
  '두 수령 주기를 고정 14일로 안내하지 않는다. 재접속이나 초기화 시점에도 계정 공통 잔여 횟수가 일치해야 한다.'),
 'tacet': (
  '에코 옵션을 선별할 때 불합격 후보의 경험치는 75%, 튜너는 30%만 돌려받는다. 선별을 반복하면 경험치보다 튜너 확보가 더 큰 제약이 될 수 있다.',
  '8단계 특급 튜너를 참조 20개에서 24개로 늘리는 안을 검토한다. 행동력 60과 경험치, 옵션 확률은 유지한다.',
  '경험치를 함께 늘리기보다 선별 과정에서 더 많이 잃는 튜너의 공급 비율을 맞춘다. 같은 단계의 무음구역에 공통 적용해야 특정 지역으로 보상 수령이 쏠리지 않는다.',
  '같은 +10 선별 조건에서 모의 평균 필요 행동력은 855.17에서 777.28로, p90은 1,580에서 1,340으로 줄었다. 중앙값은 두 안 모두 640으로 같다.',
  '유효한 세트와 주옵션 후보가 충분하고 초기 재고가 0인 조건의 계산이다. 현재 지급량을 확인해야 하며, 코인 보충 부담과 후보 확보 시간도 함께 확인한다.'),
 'tower': (
  '도전 초중반에서 얻는 보상의 비중을 높이면 완주 전에도 성과를 체감하도록 설계할 수 있다. 다만 상위 구간의 도전 이유도 남겨야 한다.',
  '36별 보상 구성의 최대 별의 소리 800개를 유지하며, 24별까지의 보상을 600개에서 640개로 옮긴다.',
  '앞 8개 구간은 각각 80개, 뒤 4개 구간은 각각 40개로 배치한다. 최대량을 늘리지 않고 보상을 받는 시점을 앞당기는 안이다.',
  '24별에서 멈추는 이용자는 40개를 더 받고, 36별까지 완료한 이용자는 기존과 같은 800개를 받는다.',
  '최대량이 같아도 초중반 달성자가 많으면 실제 발행량은 늘어난다. 구간별 달성률과 상위 도전 참여를 함께 확인한다.'),
 'whimpering': (
  '일반 도전과 추가 고점 도전은 도달 가능한 이용자 범위가 다르다. 핵심 보상의 일부를 일반 구간에서 받도록 분배를 검토한다.',
  '예시 시즌 25의 별의 소리 800개를 유지하며 일반 구간 650개, 추가 구간 150개로 조정한다.',
  '일반 첫 구간에 25개를 더하고 추가 첫 구간에서 25개를 옮긴다. 전체 분배를 바꾸기보다 진입 구간에 한정해 효과를 확인한다.',
  '기준 분배 625개와 175개를 650개와 150개로 바꾸면 일반 구간의 비중은 78.125%에서 81.25%가 된다.',
  '시즌 0의 최초 보상과 반복 시즌 보상을 합산하지 않는다. 예시 시즌의 분배를 현행 시즌에 적용하려면 활성 보상 구성을 먼저 대조해야 한다.'),
 'matrix': (
  '기본 파티 운용에서 다수 파티 도전으로 넘어갈 이유를 만들되, 여러 파티를 육성한 가치도 보존해야 한다.',
  '점수 보상 50개를 안정 프로토콜로 옮기고 3개와 4개 파티 달성 보상은 유지한다.',
  '진입 구간의 보상을 높이면서도 점수와 파티 수라는 서로 다른 성과를 계속 보상하는 안이다.',
  '안정 프로토콜의 점수 보상은 150개에서 200개, 확장의 해당 점수 보상은 150개에서 100개가 된다. 다중 파티 보상 100개를 포함한 주기 최대량 400개는 같다.',
  '점수만 높이는 것과 5,000점 이상인 파티 수를 늘리는 것을 별도 지표로 본다. 적용 주기와 보상 연결을 확인해야 한다.'),
 'hologram': (
  '홀로그램은 보스 패턴을 익히는 최초 클리어 도전이다. 초반 학습의 성과를 보상하면서 반복 재료 파밍을 강요하지 않는 방향으로 설계한다.',
  '입구별 별의 소리 총량의 절반을 첫 두 난이도에, 나머지 절반을 뒤 네 난이도에 배치한다.',
  '총량을 유지한 채 보상을 받는 시점을 앞당긴다. 반복 도전의 목적은 기록과 숙련 향상으로 둔다.',
  '각 입구의 기존 총량을 기준으로 50%와 50%로 나눈다. 정수로 나누고 남는 수량은 마지막 난이도에서 정산한다.',
  '입구마다 총량이 같다고 가정하지 않는다. 최초 클리어 보상이 재도전에서 다시 지급되지 않게 확인한다.'),
 'nightmare': (
  '에코를 많이 얻어도 원하는 세트와 주옵션이 맞지 않으면 육성 후보가 늘지 않는다. 전체 획득량보다 실제로 쓸 후보를 얻는 속도가 중요하다.',
  '후보 확률 변경은 보류하고 세트, 주옵션, 획득 시간과 튜너 재고를 함께 측정한다.',
  '세트 확률과 주옵션 확률을 따로 곱하면 실제 조합 분포를 놓칠 수 있다. 두 조건을 동시에 만족한 후보를 직접 센다.',
  '유효 후보 비율은 원하는 세트와 주옵션이 함께 맞는 후보 수를 전체 후보 수로 나눈 값이다. 후보 시간은 그 조건의 에코를 얻기까지 실제로 플레이한 시간이다.',
  '후보를 늘렸을 때 육성하지 못한 재고만 쌓이는지도 본다. 후보 확보 시간과 튜너 확보에 쓰는 행동력을 혼합하지 않는다.'),
 'nest': (
  '군락을 도는 효율에는 전투뿐 아니라 이동과 인벤토리 정리 시간이 포함된다. 전투 시간만 비교하면 실제 반복 부담을 놓친다.',
  '지급량 변경은 보류하고 경로별 유효 후보와 이동, 전투, 정리 시간을 함께 비교한다.',
  '같은 수의 후보라도 확보까지 걸리는 전체 시간이 다르면 이용자가 체감하는 효율이 달라진다.',
  '경로 효율은 유효 후보 수를 이동과 전투, 정리에 쓴 전체 시간으로 나눠 비교한다. 군락별 초기화 주기도 별도로 기록한다.',
  '확인되지 않은 초기화 주기를 무제한 반복으로 가정하지 않는다. 후보가 늘어도 튜너 부족으로 육성이 멈추는지 함께 본다.'),
 'weekly_rogue': (
  '주기 점수로 받는 무료 보상과 검은 꽃에서 행동력을 쓰고 받는 재료는 서로 다른 보상 경로다. 합쳐서 효율을 계산하면 선택이 왜곡된다.',
  '무료 점수 보상과 행동력 60의 수령 보상을 나누고, 같은 단계 무음구역과 재료 효율을 비교한다.',
  '무료 참여 성과는 별도로 유지하고 행동력을 쓸 콘텐츠는 재료별 효율을 보고 고를 수 있게 한다.',
  '비교 목표인 ±5%는 현재 확인된 차이가 아니라 검토용 기준이다. 실제 경험치와 튜너 지급 묶음을 확보한 뒤 차이를 계산한다.',
  '여러 주기의 보상을 동시에 받을 수 있는 것으로 합산하지 않는다. 주간 통화 상한 3,800도 실제 활성 경로와 대조한다.'),
 'tutorial': (
  '공명자의 핵심 전투 방식을 배웠다는 결과와 보상을 연결해야 한다. 같은 학습을 반복 진입해도 최초 보상이 중복 지급되면 안 된다.',
  '기존 최초 보상을 유지하고 핵심 전투 동작을 수행했는지 완료 조건으로 확인한다.',
  '보상 증액보다 실제 전투에서 배운 동작을 사용할 수 있는지가 이 콘텐츠의 목적에 가깝다.',
  '수령 가능 여부는 해금, 학습 완료, 미수령을 함께 확인한다. 이름이 같은 등록 항목도 같은 보상인지 별도 보상인지 식별해야 한다.',
  '등록 행 수를 서로 다른 공명자 수로 읽지 않는다. 학습 완료율과 실제 전투의 핵심 동작 사용률을 나눠 확인한다.'),
 'training': (
  '기본 훈련은 실패 원인을 이해하고 다시 시도할 수 있어야 한다. 반복 보상보다 조작을 익히는 피드백이 중요하다.',
  '최초 보상은 유지하고 실패한 동작과 다시 시도할 구간을 명확히 보여준다.',
  '학습은 여러 번 가능하게 하되 보상은 최초 완료에 연결한다. 연습 횟수와 보상 수령 횟수를 분리한다.',
  '같은 훈련을 재시도했을 때 요구 동작의 성공률이 높아지는지 확인한다. 보상은 같은 수령 대상에 한 번만 지급한다.',
  '입력 장치별로 중도 종료가 몰리는지 본다. 재입장해도 최초 수령 기록이 초기화되면 안 된다.'),
 'daily': (
  '일일 보상이 특정 던전의 추가 반복을 강제하면 평소 하려던 성장 활동과 충돌할 수 있다.',
  '별의 소리 최대 60개를 유지하고 여러 성장 활동으로 활동도 100을 채울 수 있게 한다.',
  '기존 플레이가 일일 목표로 이어지게 하는 것이 목적이다. 보상 총량보다 달성 경로와 추가 소요 시간을 확인한다.',
  '활동도 20, 40, 60, 80, 100의 구간 보상을 합한 별의 소리는 60개다. 활동도가 높아질 때 이미 받은 구간을 다시 지급하지 않는다.',
  '주간 목표와 일일 초기화 시간을 혼합하지 않는다. 목표를 달성하고도 보상을 받지 못하는 비율을 확인한다.'),
 'double_reward': (
  '두 배 보상은 정해진 횟수에만 적용된다. 남은 횟수나 대상 재료를 잘못 이해하면 원하지 않는 곳에 행동력을 쓸 수 있다.',
  '3회와 2배의 보상 구성을 유지하고 남은 적용 횟수와 대상 콘텐츠를 표시한다.',
  '추가 보상이 붙는 횟수와 기본 수령을 구분해야 발행 예산과 이용자 안내가 일치한다.',
  '네 번 수령하고 그중 세 번이 두 배라면 기본 4회분에 추가 3회분을 더해 총 7회분이다. 네 번 모두 두 배인 8회분이 아니다.',
  '이벤트가 종료되면 기본 공급으로 돌아간다. 종료 후 경험치와 튜너 부족이 어떻게 바뀌는지도 확인한다.'),
 'rogue_archive': (
  '한 번의 도전 안에서 쓰는 통화와 계정에 남는 성장 보상은 역할이 다르다. 과거 시즌 보상까지 합치면 현재 공급량을 과대평가할 수 있다.',
  '활성 시즌의 계정 보상만 집계하고 핵심 성장 재료를 대표적인 플레이 경로에 우선 배치한다.',
  '특정 희귀 조합을 찾기 위한 반복이 필수 성장 경로가 되지 않도록 한다. 도전 내부의 성장 통화는 별도로 관리한다.',
  '보상표에서 도전 종료 시 사라지는 재화와 계정으로 가져오는 재화를 구분한다. 계정 공급량에는 후자만 포함한다.',
  '시즌별 수령 기록과 소멸 조건을 확인한다. 특정 조합이 지나치게 유리해 다른 조합의 선택이 사라지는지도 본다.'),
 'event_framework': (
  '기간 콘텐츠마다 참여, 숙련, 수집, 반복 보상이 섞여 있으면 기본 보상까지 필요한 시간과 예산을 비교하기 어렵다.',
  '보상을 참여, 숙련, 수집, 반복으로 나누고 각 경로의 조건과 예산, 종료 후 처리를 정한다.',
  '핵심 정기 통화는 기본 참여 경로에서 얻도록 하고 높은 숙련이나 수집 목표는 별도로 설계한다.',
  '수령 가능 여부는 진행 기간, 참여 자격, 완료 조건, 미수령 상태를 함께 확인한다. 등록된 392개 항목을 현재 진행 중인 이벤트 수로 사용하지 않는다.',
  '기본 보상까지 걸리는 시간과 실제 수령 비율로 비교한다. 종료 직전 완료한 보상과 미수령 보상의 처리도 정해야 한다.'),
}

CSS = '''
/* Reading edition: intent first, evidence remains available. */
body{font-size:16px;line-height:1.9;word-break:keep-all;overflow-wrap:break-word;background:#edf1f2}
main{max-width:1120px;margin:24px auto;padding:38px 48px 65px;box-shadow:0 8px 30px #18313b0a}
header{margin-bottom:22px}h1{font-size:2rem;line-height:1.45}h2{font-size:1.42rem;margin:38px 0 16px;padding-top:20px}h3{font-size:1.08rem}
p,li{max-width:900px}p{margin:14px 0}.callout{font-size:1.12rem;line-height:1.9;padding:22px 25px;font-weight:550;border-radius:0 8px 8px 0}
.reading-map{display:flex;gap:10px 20px;flex-wrap:wrap;padding:13px 18px;background:#f5f8f9;border:1px solid #e1e8eb;font-size:.82rem;margin:22px 0}.reading-map a{text-decoration:none}
.plain-example{padding:19px 23px;border-radius:9px;background:#f0f7f5;border-left:4px solid #3b8d81}.plain-example p{margin:5px 0}.condition{font-size:.87rem;color:#455e6b;padding:14px 18px;background:#f5f7f8;border-radius:7px}
.decision-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.decision-card{padding:18px 20px;border:1px solid #d7e3e6;border-radius:8px}.decision-card strong{display:block;font-size:.95rem;color:#146e66}.decision-card p{font-size:.85rem;margin:8px 0 0}
table{font-size:.87rem;line-height:1.75}th,td{padding:13px 15px}th{color:#244653}td{min-width:80px}.scroll{margin:20px 0}.selected{background:#e9f6f1}
details{margin:24px 0;padding:16px 20px;background:#fbfcfd;border-radius:8px}details h2{font-size:1.1rem;margin-top:23px}summary{color:#285562;font-size:.9rem}details[open]>summary{padding-bottom:12px;border-bottom:1px solid #d9e3e7}.term-note{font-size:.8rem;color:#506671}
.reading-tools{margin-left:auto}.icon-nav{position:static;align-items:center;gap:16px;font-size:.8rem}.icon-nav button{font:inherit;padding:6px 12px;border:1px solid #cbdce0;background:white;border-radius:5px;cursor:pointer}
.resource-guide{margin:25px 0}.resource-guide h2{font-size:.94rem}.resource-card small{font-size:.74rem}.steps{padding-left:25px}.steps li{padding:4px 0 4px 5px}.sources li{margin:5px 0}
@media(max-width:700px){main{margin:0;padding:24px 20px}h1{font-size:1.5rem}h2{font-size:1.24rem}.callout{font-size:1rem;padding:17px 18px}.decision-cards{grid-template-columns:1fr}.reading-map{gap:10px 14px}.icon-nav .reading-tools{margin-left:0}.plain-example{padding:16px 18px}.scroll table{min-width:610px}details{padding:13px 14px}th,td{padding:10px}.icon-heading{align-items:flex-start}}
@media print{@page{size:A4;margin:14mm 12mm}body{font-size:10pt;line-height:1.6;background:white}main{margin:0;padding:0;box-shadow:none}.icon-nav,.reading-map{display:none}h1{font-size:21pt}h2{font-size:15pt;break-after:avoid}h3{break-after:avoid}.callout{font-size:11pt;padding:16px 20px}table{font-size:8pt;min-width:0!important}th,td{padding:7px}.scroll{overflow:visible}.plain-example,.condition,.decision-cards,summary,.sources li{break-inside:avoid}.resource-guide{break-inside:avoid}.game-icon,.selected,.plain-example{-webkit-print-color-adjust:exact;print-color-adjust:exact}details{border:0;padding:0;background:white}details>summary{font-size:11pt}p{widows:3;orphans:3}}
'''
JS = '''
window.addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>{d.dataset.readerWasOpen=d.open?'1':'0';d.open=true}));
window.addEventListener('afterprint',()=>document.querySelectorAll('details').forEach(d=>{d.open=d.dataset.readerWasOpen==='1'}));
'''

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v): Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def para(s, cls=''): return node('p',s,**({'class':cls} if cls else {}))
def heading(s): return node('h2',s)
def table(heads,rows):
    return node('div',node('table',node('thead',node('tr',*[node('th',h,scope='col') for h in heads])),node('tbody',*[node('tr',*[node('td',c if isinstance(c,Node) else str(c)) for c in row]) for row in rows])),**{'class':'scroll'})
def link(label,href): return node('a',label,href=href)
def folded(label,children): return node('details',node('summary',label),*deepcopy(children),**{'class':'technical-details'})

def blocks(main):
    groups={};current=None
    for c in main.children:
        if isinstance(c,Node) and c.tag=='h2':current=c.text();groups[current]=[]
        elif current is not None and isinstance(c,Node) and c.tag!='footer':groups[current].append(c)
    return groups

def plain(s):
    for a,b in [('+25 완성 경험치까지 함께 인플레이션시키지 않음','경험치 공급까지 동시에 늘리지 않음'),('통합 재화 인플레이션 방지','공통 재화의 과도한 공급 방지'),('동일 코호트','비슷한 조건의 이용자 집단'),('코호트','이용자 집단'),('쿼터','수령 가능 횟수'),('꼬리 편차','오래 걸리는 경우의 편차'),('녹색환산','녹색 재료 기준 수량'),('인플레이션','과도한 재화 공급')]:s=s.replace(a,b)
    return s

def simplify(n):
    for i,c in enumerate(n.children):
        if isinstance(c,Node):
            if c.tag not in ('script','style','code'):simplify(c)
        else:n.children[i]=plain(c)

def to_md(n,page,out,in_cell=False):
    if not isinstance(n,Node):return n
    tag=n.tag
    if tag in ('script','style','head','button','input','select','output'):return ''
    inside=''.join(to_md(c,page,out,in_cell) for c in n.children)
    if tag in ('h1','h2','h3','h4'):
        anchor='<a id="'+n.attrs['id']+'"></a>\n\n' if 'id' in n.attrs else ''
        return '\n\n'+anchor+'#'*int(tag[1])+' '+inside.strip()+'\n\n'
    if tag=='img':
        src=n.attrs.get('src','');alt=n.attrs.get('alt','')
        return f'<img src="{src}" alt="{alt}" width="32" height="32" style="background:#27313b;border-radius:5px;vertical-align:middle;padding:2px"> '
    if tag=='a':
        href=n.attrs.get('href','')
        u=urlsplit(href)
        if not u.scheme and u.path.endswith('.html'):
            target=Path(os.path.normpath(page.parent/u.path)).with_suffix('.md')
            if target.exists() or not u.path.startswith('../..'):
                href=href.replace('.html','.md')
        return '['+inside.strip()+'](<'+href+'>)'
    if tag=='br':return '<br>' if in_cell else '\n'
    if tag in ('strong','b'):return '**'+inside.strip()+'**'
    if tag=='code':return '`'+inside.strip()+'`'
    if tag=='table':
        rs=[]
        for row in n.walk('tr'):
            cells=[to_md(c,page,out,True).strip().replace('\n','<br>').replace('|','\\|') for c in row.children if isinstance(c,Node) and c.tag in ('th','td')]
            rs.append('| '+' | '.join(cells)+' |')
        if not rs:return ''
        count=sum(isinstance(c,Node) and c.tag in ('th','td') for c in next(n.walk('tr')).children)
        rs.insert(1,'| '+' | '.join('---' for _ in range(count))+' |')
        return '\n\n'+'\n'.join(rs)+'\n\n'
    if tag=='ol':
        return '\n\n'+'\n'.join(str(i)+'. '+to_md(c,page,out).strip() for i,c in enumerate((c for c in n.children if isinstance(c,Node) and c.tag=='li'),1))+'\n\n'
    if tag=='ul':return '\n\n'+'\n'.join('- '+to_md(c,page,out).strip() for c in n.children if isinstance(c,Node) and c.tag=='li')+'\n\n'
    if tag=='details':
        summary=next((c for c in n.children if isinstance(c,Node) and c.tag=='summary'),None)
        body=''.join(to_md(c,page,out) for c in n.children if c is not summary)
        return '\n\n<details>\n<summary>'+summary.text()+'</summary>\n\n'+body.strip()+'\n\n</details>\n\n'
    if tag=='summary':return ''
    if tag=='nav':return '\n\n'+' · '.join(to_md(c,page,out).strip() for c in n.children if isinstance(c,Node) and c.tag!='button')+'\n\n'
    if tag=='div' and n.attrs.get('class')=='reading-map':return '\n\n'+' · '.join(to_md(c,page,out).strip() for c in n.children)+'\n\n'
    if tag=='div' and 'formula' in n.attrs.get('class',''):return '\n\n```text\n'+n.text()+'\n```\n\n'
    if tag in ('p','nav','aside','section','header','footer') or tag=='div' and n.attrs.get('class') in ('callout','plain-example','decision-card'):
        return ('<br>' if in_cell else '\n\n')+inside.strip()+('<br>' if in_cell else '\n\n')
    return inside

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--run',type=Path,required=True);a=ap.parse_args()
    source,out,run=a.source.absolute(),a.out.absolute(),a.run.absolute()
    if out.exists():raise ValueError('Output must be a new directory')
    parent=load(source/'문서_명세.json')
    for rel,digest in parent['files'].items():
        if sha(source/rel)!=digest:raise ValueError('Source changed: '+rel)
    plans={p['id']:p for p in load(EVIDENCE/'기획_정의.json')['plans']}
    assert set(plans)==set(BRIEFS)
    study=load(BASE/'결과/20261118_중부평원_단일보고서/대안_비교/결과.json')
    counts=load(EVIDENCE/'콘텐츠_근거.json')['catalog']
    shutil.copytree(source,out,copy_function=shutil.copyfile);run.mkdir(parents=True,exist_ok=True)
    (out/'readable.css').write_text(CSS,encoding='utf-8');(out/'reader.js').write_text(JS,encoding='utf-8')
    changed=[]
    for page in sorted(out.rglob('*.html')):
        rel=page.relative_to(out);parsed=Parser(page.read_text(encoding='utf-8')).root
        head=next(parsed.walk('head'));body=next(parsed.walk('body'));main=next(parsed.walk('main'))
        prefix=os.path.relpath(out,page.parent).replace(os.sep,'/')
        head.children.append(node('link',rel='stylesheet',href=prefix+'/readable.css'))
        body.children.append(node('script',src=prefix+'/reader.js'))
        original=deepcopy(main.children);g=blocks(main);edited=False
        nav=next((c for c in main.children if isinstance(c,Node) and c.tag=='nav'),None)
        if nav:
            nav.children += [link('용어 설명',prefix+'/쉬운_용어_안내.html'),node('button','인쇄 / PDF',type='button',onclick='window.print()',**{'class':'reading-tools'})]
        if rel.parts[0] in ('기획서','제안서') and page.stem in plans:
            cat=page.stem;p=plans[cat];problem,decision,reason,example,risk=BRIEFS[cat]
            top=[c for c in main.children if isinstance(c,Node) and c.tag in ('header','nav')]
            foot=[c for c in main.children if isinstance(c,Node) and c.tag=='footer']
            resource=next((c for c in original if isinstance(c,Node) and c.attrs.get('class')=='resource-guide'),None)
            if resource is None and rel.parts[0]=='제안서':
                source_plan=Parser((source/'기획서'/(cat+'.html')).read_text(encoding='utf-8')).root
                resource=next((c for c in source_plan.walk('aside') if c.attrs.get('class')=='resource-guide'),None)
            rows=deepcopy(p['changes'])
            for row in rows:
                row[0]=re.sub(r'\s*\(Drop [^)]+\)','',row[0])
                if row[0] in ('보상 안내','예상 횟수 안내','성장 화면','성장 예약','대상 선택','수령 안내','선별 안내','반복 편의','사전 안내'):
                    row[1]='현행 화면 확인 후 적용 범위 확정'
            if cat=='event_framework':rows[-1][3]='합계, 중복 수령, 종료 시 처리를 검수'
            if cat=='tacet':rows[1][1]='과거 평균 24,154.98 EXP/회'
            content=top+[node('div',decision,**{'class':'callout'}),para('자료 기준: 설치본 3.8.0, 공식 공시, 과거 공개 실측. 변경값은 적용을 검토할 설계안이다.','term-note'),heading('해결할 문제'),para(problem)]
            if resource:content.append(resource)
            content += [heading('변경 전후'),table(['항목','비교 기준','설계안','이유'],rows)]
            if rel.parts[0]=='기획서':
                content += [heading('플레이 흐름'),node('ol',*[node('li',s.replace('폐기 및 환급 재사용','성장 재료로 재사용')) for s in p['loop']],**{'class':'steps'})]
            content += [heading('이렇게 설계하는 이유'),para(reason)]
            if cat=='tacet':content.append(para('계산 조건: 유효한 세트·주옵션 후보 충분, 초기 재고 0, 일반 튜닝, 과거 지급 자료, 같은 5,000회 시행.','term-note'))
            content.append(node('div',node('strong','구체적인 예'),para(example),**{'class':'plain-example'}))
            if cat=='tacet':
                content.append(para('쌍크리는 크리티컬과 크리티컬 피해가 함께 붙은 에코를 뜻한다. +10 선별은 첫 두 옵션에 둘 중 하나도 없으면 해당 후보를 성장 재료로 재사용하는 방식이다. 수치 최저선은 두지 않았다.','term-note'))
                if rel.parts[0]=='제안서':
                    content += [heading('왜 24개인가'),table(['비교안','평균 필요 행동력','p90 행동력','240 행동력당 추가 튜너'],[[r['name'],f'{r["days"]["mean"]*240:,.2f}',f'{r["days"]["p90"]*240:,.0f}',str(r['tuner_supply_per_240_waveplates']-80)+'개'] for r in study['arms']]),para('경험치는 유지하고 추가 튜너는 240 행동력당 16개 이내로 제한하면서, 표본 p90을 행동력 1,440 이하로 낮추는 것을 검토 기준으로 삼았다. 비교한 다섯 안 중 24개안이 이 조건에 맞는다.'),para('24개안의 p90 모의 오차 구간은 1,280~1,460 행동력으로 목표 1,440을 걸친다. 현재 지급량을 반영한 추가 검증 후 적용을 판단한다. 경험치 10% 증가는 경험치 환산량을 늘린 비교용 모형이다.','condition')]
                content.append(para(link('중부 평원 사례에서 재화 흐름과 계산 보기',os.path.relpath(CASE,page.parent).replace(os.sep,'/'))))
            content += [heading('효과를 확인하는 방법'),para('아래 수치 중 제안 기준은 적용 여부를 판단하기 위한 목표다. 실제 이용자 성과는 같은 버전과 성장 조건에서 비교한다.'),table(['확인 항목','계산하거나 관찰할 내용','비교할 집단','판단 기준'],p['kpis']),para(risk,'condition')]
            if rel.parts[0]=='기획서':
                content += [heading('반드시 지킬 조건'),node('ul',*[node('li',s) for s in p['checks']])]
                detail=[]
                for title in ('계산 가능한 설계 모델','상태·예외·수령 계약','적용 대상 목록'):
                    if g.get(title):detail += [node('h3',title)]+g[title]
                content.append(folded('개발 참고 · 계산식, 수령 처리, 적용 대상',detail))
            else:
                content += [heading('적용과 검증 순서'),node('ol',node('li','현재 버전의 실제 지급량과 이용자 진행 상태를 먼저 확인한다.'),node('li','정해진 단계와 주기에만 설정을 연결하고 비용, 중복 수령, 초기화 처리를 검수한다.'),node('li','성장 단계와 초기 재고가 비슷한 이용자 집단에서 목표 지표와 다른 재화의 부족을 함께 비교한다.'),node('li','예상과 다른 지급이나 성장 제약이 생기면 확대를 보류하고 해당 설정을 복구한다.'),**{'class':'steps'})]
                detail=[]
                for title in ('문제 가설과 선택','대안 비교와 채택 근거','대안과 제외 이유','설정값 전후와 예산 검사'):
                    if g.get(title):
                        cells=g[title]
                        if title=='문제 가설과 선택':cells=[c for c in cells if not(isinstance(c,Node) and c.attrs.get('class')=='scroll')]
                        detail += [node('h3',title)]+cells
                content.append(folded('상세 근거 · 관측 자료, 대안, 설정값 비교',detail))
            content += [heading('근거와 연결 문서')]+g.get('근거와 연결 문서',[])+foot
            main.children=content;edited=True
        elif rel.parts[0]=='분석서' and page.stem in plans:
            cat=page.stem;problem,decision,reason,example,risk=BRIEFS[cat]
            # Keep every original observation, formula and reward cell intact.
            idx=next(i for i,c in enumerate(main.children) if isinstance(c,Node) and c.tag=='h2')
            main.children[idx:idx]=[heading('이 분석에서 확인할 것'),para(problem)]
            edited=True
        elif rel.as_posix()=='기획서/00_통합기획서.html':
            top=[c for c in main.children if isinstance(c,Node) and c.tag in ('header','nav')];foot=[c for c in original if isinstance(c,Node) and c.tag=='footer']
            main.children=top+[node('div','필요한 재료를 예측하며 성장하고, 도전한 만큼 보상을 체감하도록 설계한다.',**{'class':'callout'}),heading('세 가지 설계 방향'),node('div',node('div',node('strong','선별에 필요한 재료 맞추기'),para('무음구역은 에코 경험치보다 빠르게 소모되는 튜너의 공급 비율을 조정한다.'),**{'class':'decision-card'}),node('div',node('strong','완주 전의 성과 보상하기'),para('도전 콘텐츠는 최대량을 유지하면서 초중반 구간에서 받는 보상을 늘리는 안을 검토한다.'),**{'class':'decision-card'}),node('div',node('strong','다음 성장 행동 알려주기'),para('재고와 목표 비용, 남은 주간 수령 횟수를 함께 보여줘 필요한 콘텐츠를 고르게 한다.'),**{'class':'decision-card'}),**{'class':'decision-cards'}),heading('설계 의도와 확인할 결과')]+g['설계 목적과 성공 조건']+[heading('이용자의 성장 흐름'),para('목표를 고른다 → 부족한 재료와 해금 조건을 확인한다 → 콘텐츠를 선택한다 → 보상을 받는다 → 성장시킨다 → 도전에서 성과를 확인한다.'),heading('한 사례로 이해하기'),para(BRIEFS['tacet'][0]),para(BRIEFS['tacet'][1]),node('div',para(BRIEFS['tacet'][3]),**{'class':'plain-example'}),para(BRIEFS['tacet'][4],'condition'),para(link('중부 평원 무음구역의 단일 보고서',os.path.relpath(CASE,page.parent).replace(os.sep,'/'))),heading('콘텐츠별 설계 핵심'),table(['콘텐츠','설계할 내용'],[[link(p['title'],cat+'.html'),BRIEFS[cat][1]] for cat,p in plans.items()]),folded('상세 참고 · 계산 모델과 공통 검수 조건',[node('h3','계산 모델')]+g['수학 모델과 설계 규칙 대응']+[node('h3','검수 조건')]+g['공통 검수 조건'])]+foot
            edited=True
        elif rel.as_posix()=='제안서/00_개선안_의사결정.html':
            top=[c for c in main.children if isinstance(c,Node) and c.tag in ('header','nav')];foot=[c for c in original if isinstance(c,Node) and c.tag=='footer']
            first_table=next(c for c in original if isinstance(c,Node) and c.attrs.get('class')=='scroll')
            main.children=top+[node('div','튜너 공급과 성장 안내를 우선 검토하고, 도전 보상 재분배는 실제 지급량 증가를 확인한 뒤 판단한다.',**{'class':'callout'}),heading('우선순위와 판단 이유'),first_table,heading('무음구역 24개안을 고른 이유'),para(BRIEFS['tacet'][0]),para(BRIEFS['tacet'][2]),node('div',para(BRIEFS['tacet'][3]),**{'class':'plain-example'}),para('비교한 다섯 안 중 경험치 유지, 추가 튜너 16개 이내, 표본 p90 행동력 1,440 이하라는 검토 기준을 충족한 안이다. 현재 지급을 반영한 검증을 거쳐 적용을 판단한다.'),para(link('대안별 수치와 선택 조건 보기','tacet.html')),heading('보상 재분배에서 주의할 점'),para('역경의 탑은 24별까지의 별의 소리를 600개에서 640개로 늘리고 36별 최대 800개는 유지한다. 완주하지 못한 이용자에게 지급되는 양이 늘므로 전체 실제 발행량은 증가할 수 있다.'),heading('적용 전 확인할 내용')]+g['적용 판단에 필요한 증거']+[heading('콘텐츠별 제안'),table(['콘텐츠','제안 방향'],[[link(p['title'],cat+'.html'),BRIEFS[cat][1]] for cat,p in plans.items()]),folded('상세 비교 · 무음구역의 모의 계산',g['무음구역의 대안 선택'])]+foot
            edited=True
        elif page.name=='index.html' and rel.parts[0] in ('기획서','분석서','제안서'):
            for t in main.walk('table'):
                headers=[h.text() for h in t.walk('th')]
                if headers==['콘텐츠','개별 가이드 수','모델']:
                    for h,s in zip(t.walk('th'),['콘텐츠','등록된 대상 수','이 문서에서 다루는 내용']):h.children=[s]
                    for row,(cat,p) in zip(next(t.walk('tbody')).children,plans.items()):
                        cells=[c for c in row.children if isinstance(c,Node) and c.tag=='td'];cells[-1].children=[BRIEFS[cat][1] if rel.parts[0]!='분석서' else BRIEFS[cat][3]]
            edited=True
        elif rel.as_posix()=='index.html':
            top=[c for c in main.children if isinstance(c,Node) and c.tag in ('header','nav')];foot=[c for c in original if isinstance(c,Node) and c.tag=='footer']
            cards=next(c for c in original if isinstance(c,Node) and c.attrs.get('class')=='cards')
            resource=next(c for c in original if isinstance(c,Node) and c.attrs.get('class')=='resource-guide')
            main.children=top+[node('div','명조의 보상 구조를 이해하고, 무엇을 바꿀지 판단하는 문서 모음입니다.',**{'class':'callout'}),heading('한 던전의 사례부터 읽기'),node('div',node('strong','중부 평원 무음구역'),para('재화를 어디서 얻고 어디에 쓰는지 살펴본 뒤, 튜너 20개와 24개안을 같은 조건에서 비교합니다.'),para(link('재화 구조 분석과 개선안 열기',os.path.relpath(CASE,page.parent).replace(os.sep,'/'))),**{'class':'plain-example'}),heading('목적에 맞는 문서 고르기'),cards,heading('권장 읽기 순서'),node('ol',node('li',link('통합 기획서','기획서/00_통합기획서.html'),'에서 설계 목적과 바꿀 규칙을 확인합니다.'),node('li',link('통합 제안서','제안서/00_개선안_의사결정.html'),'에서 우선순위와 선택 이유를 봅니다.'),node('li',link('분석서','분석서/index.html'),'에서 필요한 수식, 표본, 원본 근거를 찾아봅니다.'),**{'class':'steps'}),resource,heading('자료를 읽는 기준'),para('콘텐츠 구조와 성장 비용은 설치본 3.8.0, 보상 비교는 공식 공시와 과거 공개 실측을 근거로 합니다. 설계안과 현행 지급은 구분해 읽어야 합니다. 과거 표본과 현재 서버의 차이는 각 적용 단계에서 확인합니다.'),folded('문서 범위와 이전 자료',g['범위와 상태']+g['이전 화면의 예시게임 안내'])]+foot
            edited=True
        if edited:
            simplify(main)
            texts=main.text()
            terms=[]
            if 'p90' in texts:terms.append('p90은 결과를 작은 값부터 정렬했을 때 90% 지점이며, 오래 걸리는 경우를 보는 지표다.')
            if '환산일' in texts:terms.append('환산일은 필요 행동력을 240으로 나눈 값으로, 실제 플레이 기간과 다르다.')
            if terms:
                idx=next((i for i,c in enumerate(main.children) if isinstance(c,Node) and c.tag=='h2'),len(main.children)-1)
                main.children.insert(idx,para(' '.join(terms),'term-note'))
            hs=[c for c in main.children if isinstance(c,Node) and c.tag=='h2']
            if len(hs)>2 and page.name!='index.html':
                for i,h in enumerate(hs,1):h.attrs['id']='read-'+str(i)
                toc=node('div',*[link(h.text(),'#'+h.attrs['id']) for h in hs],**{'class':'reading-map'})
                idx=next(i for i,c in enumerate(main.children) if isinstance(c,Node) and c.tag=='h2');main.children.insert(idx,toc)
            md=to_md(main,page,out);page.with_suffix('.md').write_text(re.sub(r'\n{3,}','\n\n',md).strip()+'\n',encoding='utf-8')
            changed.append(rel.as_posix())
        page.write_text('<!doctype html>\n'+parsed.html()+'\n',encoding='utf-8')
    glossary=[('경험치와 EXP','같은 뜻이다. 문서에서 EXP는 아이템 개수가 아니라 경험치로 환산한 양을 가리킨다.'),('튜너','에코의 부옵션을 여는 재료다. 레벨을 올리는 경험치 재료와 역할이 다르다.'),('쌍크리','크리티컬과 크리티컬 피해가 함께 붙은 에코다. 두 옵션의 수치 조건을 요구하는지는 계산마다 구분한다.'),('선별','중간에 공개된 옵션을 보고 계속 성장시킬 후보와 재료로 재사용할 후보를 고르는 행동이다.'),('p50과 p90','작은 값부터 정렬했을 때 각각 50%, 90% 지점이다. p50은 중앙값, p90은 비교적 오래 걸리는 경우를 보는 지표다.'),('환산일','필요 행동력을 240으로 나눈 비교 단위다. 후보 확보, 전투, 해금, 접속 일정까지 포함한 실제 날짜가 아니다.'),('녹색 재료 기준 수량','같은 계열의 높은 등급 재료를 합성 비율에 따라 녹색 재료 수량으로 바꾼 값이다. 다른 계열끼리는 합산하지 않는다.'),('공유 수령 횟수','여러 콘텐츠가 함께 사용하는 제한이다. 한 보스에서 사용하면 다른 보스에서 남은 횟수도 줄어든다.'),('최대 보상과 실제 지급량','최대 보상은 모든 조건을 완료할 때 받을 수 있는 양이다. 실제 지급량은 이용자들이 어느 조건까지 완료했는지에 따라 달라진다.'),('표본과 오차 구간','표본은 모은 관측이나 계산 결과다. 오차 구간은 지정한 계산 조건의 불확실성을 나타내며 버전 변화나 이용자 편향을 모두 포함하지 않을 수 있다.')]
    title='명조 보상 문서의 쉬운 용어 안내'
    gm=node('main',node('header',node('h1',title)),node('nav',link('문서 모음','index.html'),**{'class':'icon-nav'}),para('재화의 역할과 계산에서 쓰는 단위를 설명합니다.'),*[node('section',heading(t),para(s)) for t,s in glossary])
    doc=node('html',node('head',node('meta',charset='utf-8'),node('meta',name='viewport',content='width=device-width,initial-scale=1'),node('title',title),node('link',rel='stylesheet',href='style.css'),node('link',rel='stylesheet',href='readable.css')),node('body',gm),lang='ko')
    gp=out/'쉬운_용어_안내.html';gp.write_text('<!doctype html>\n'+doc.html(),encoding='utf-8');gp.with_suffix('.md').write_text(to_md(gm,gp,out).strip()+'\n',encoding='utf-8')
    manifest=deepcopy(parent);manifest.update(status='reading_edition_review_pending',edition='20261118_가독성개선',source_edition=str(source),source_edition_manifest_sha256=sha(source/'문서_명세.json'),readability_generator_sha256=sha(__file__),narrative_rewritten=changed,glossary='쉬운_용어_안내.html')
    manifest['files']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='문서_명세.json'}
    save(out/'문서_명세.json',manifest);save(run/'문서_생성기록.json',{'source':str(source),'output':str(out),'rewritten':changed,'styles_applied':len(list(out.rglob('*.html'))),'source_manifest_sha256':manifest['source_edition_manifest_sha256'],'generator_sha256':sha(__file__)})
    print(json.dumps({'out':str(out),'narrative_pages':len(changed),'html_pages':len(list(out.rglob('*.html')))},ensure_ascii=False))

if __name__=='__main__':main()
