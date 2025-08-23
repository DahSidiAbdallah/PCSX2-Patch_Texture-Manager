try:
    import requests
    print('requests=installed')
except Exception:
    print('requests=missing')
try:
    from bs4 import BeautifulSoup
    print('bs4=installed')
except Exception:
    print('bs4=missing')
