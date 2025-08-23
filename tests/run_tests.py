from main import parse_raw_8x8, build_pnach, PnachData


def run():
    print('Running parsing tests...')
    text = """
    00200000 00000030
    00200004, 1
    // comment
    """
    pairs = parse_raw_8x8(text)
    assert ('00200000','00000030') in pairs
    assert ('00200004','00000001') in pairs
    print(' parse_raw_8x8 basic: OK')

    pd = PnachData(crc='DEADBEEF', serials=['SLUS-21234'], title='Test Game', raw_pairs=[('00200000','00000001')])
    out = build_pnach(pd)
    assert 'gametitle=Test Game' in out
    assert 'patch=1,EE,00200000,extended,00000001' in out
    print(' build_pnach single patch: OK')

if __name__ == '__main__':
    run()
