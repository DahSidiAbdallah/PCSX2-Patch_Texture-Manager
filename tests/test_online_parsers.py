import json, os
from cheat_online import parse_psxdatacenter_html, parse_gamehacking_json, _normalize_code_lines

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_psxdatacenter_parser():
    p = os.path.join(FIX, 'psxdatacenter_sample.html')
    with open(p, 'r', encoding='utf-8') as f:
        html = f.read()
    res = parse_psxdatacenter_html(html, 'SLUS-21234')
    assert isinstance(res, list) and len(res) >= 1
    entry = res[0]
    assert 'Sample Game Title' in (entry.get('title') or '')
    assert ('00200000 00000001' in entry.get('codes') or '00200004 00000002' in entry.get('codes'))


def test_gamehacking_json_parser():
    p = os.path.join(FIX, 'gamehacking_sample.json')
    with open(p, 'r', encoding='utf-8') as f:
        obj = json.load(f)
    res = parse_gamehacking_json(obj)
    assert isinstance(res, list) and len(res) == 1
    entry = res[0]
    assert entry.get('title') == 'Sample Game'
    assert '00200000 00000001' in entry.get('codes')

def test_normalize_code_lines_edge():
    raw = ['00200000:00000001', 'Some text 00200004 00000002 extra', 'patch=1,EE,00200000,extended,00000001']
    norm = _normalize_code_lines(raw)
    assert '00200000 00000001' in norm
    assert '00200004 00000002' in norm
    assert any(l.startswith('patch=1,EE') for l in norm)

