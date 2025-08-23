import pytest
from main import parse_raw_8x8, build_pnach, PnachData


def test_parse_raw_8x8_basic():
    text = """
    00200000 00000030
    00200004, 1
    // comment
    """
    pairs = parse_raw_8x8(text)
    assert ('00200000', '00000030') in pairs
    assert ('00200004', '00000001') in pairs


def test_build_pnach_single_patch():
    pd = PnachData(crc='DEADBEEF', serials=['SLUS-21234'], title='Test Game', raw_pairs=[('00200000', '00000001')])
    out = build_pnach(pd)
    assert 'gametitle=Test Game' in out
    assert 'patch=1,EE,00200000,extended,00000001' in out

