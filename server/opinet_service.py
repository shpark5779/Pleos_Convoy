"""Server-only Opinet access. Persistent shared quota/cache; no key in client responses."""
import json
from contextlib import closing
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError
from tmap_service import km

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = {'B027':'휘발유', 'D047':'경유'}
KATEC = '+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 +ellps=bessel +towgs84=-146.43,507.89,681.46 +units=m +no_defs'


class OpinetError(Exception):
    pass


def transform(x, y, reverse=False):
    try:
        from pyproj import Transformer
    except ImportError:
        raise OpinetError('유가 좌표 변환 설치 필요: pip install -r server/requirements-opinet.txt') from None
    source, target = ('EPSG:4326', KATEC) if reverse else (KATEC, 'EPSG:4326')
    return Transformer.from_crs(source, target, always_xy=True).transform(x, y)


def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


class Opinet:
    def __init__(self, database=None):
        self.database = database or ROOT/'build/opinet-cache.sqlite'

    def config(self):
        values = {}
        if (ROOT/'.env').exists():
            for line in (ROOT/'.env').read_text('utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('\"\'')
        key = os.environ.get('OPINET_API_KEY', values.get('OPINET_API_KEY', ''))
        budget = int(os.environ.get('OPINET_DAILY_BUDGET', values.get('OPINET_DAILY_BUDGET', '280')))
        if not key:
            raise OpinetError('서버 .env에 OPINET_API_KEY를 설정하세요.')
        return key, min(280, max(1, budget))

    def request(self, endpoint, params, ttl):
        key, budget = self.config()
        cache_key = 'code:'+endpoint+json.dumps(params, sort_keys=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=20)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched REAL, data TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY, calls INTEGER)')
            # Serialize quota reservations across threads/processes sharing this project.
            db.execute('BEGIN IMMEDIATE')
            hit = db.execute('SELECT fetched,data FROM cache WHERE key=?', (cache_key,)).fetchone()
            if hit and time.time()-hit[0] < ttl:
                return json.loads(hit[1]), hit[0]
            day = time.strftime('%Y-%m-%d', time.gmtime(time.time()+9*3600))
            used = db.execute('SELECT calls FROM quota WHERE day=?', (day,)).fetchone()
            if used and used[0] >= budget:
                raise OpinetError('오피넷 일일 조회 예산을 소진했습니다. 캐시 만료 후 조회를 중단합니다.')
            db.execute('INSERT INTO quota VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))
            db.commit()  # Failed provider calls still count against our local budget.
            try:
                # This issued personal key accepts `code`; verified against live responses.
                url = 'https://www.opinet.co.kr/api/'+endpoint+'.do?'+urlencode(dict(params, code=key, out='json'))
                with urlopen(url, timeout=12) as response:
                    raw = response.read(2*1024*1024+1)
                if len(raw) > 2*1024*1024:
                    raise ValueError('Oversized response')
                data = json.loads(raw)
                rows = data['RESULT']['OIL']
                if not isinstance(rows, list):
                    raise ValueError('Invalid provider response')
            except (URLError, TimeoutError, ValueError, KeyError, TypeError, OSError):
                raise OpinetError('오피넷 조회 실패: 인증·이용 한도·연결 상태를 확인하세요.') from None
            now = time.time()
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (cache_key, now, json.dumps(rows)))
            return rows, now

    def nearby(self, latitude, longitude, product='B027'):
        if product not in PRODUCTS or not (32 <= latitude <= 40 and 123 <= longitude <= 133):
            raise OpinetError('국내 위치와 유종을 확인하세요.')
        x, y = transform(round(longitude, 3), round(latitude, 3), reverse=True)
        rows, fetched = self.request('aroundAll', {'x':round(x,1), 'y':round(y,1), 'radius':5000,
                                                  'prodcd':product, 'sort':1}, 600)
        stations = []
        for row in rows:
            price = positive(row.get('PRICE'))
            try:
                lon, lat = transform(float(row['GIS_X_COOR']), float(row['GIS_Y_COOR']))
                if not price or not (32 <= lat <= 40 and 123 <= lon <= 133):
                    continue
                if km({'latitude':latitude,'longitude':longitude},{'latitude':lat,'longitude':lon}) > 5.2:
                    continue
                stations.append({'id':str(row['UNI_ID']), 'name':str(row['OS_NM']), 'longitude':lon, 'latitude':lat,
                                 'price':price, 'product':product, 'product_name':PRODUCTS[product],
                                 'distance_m':positive(row.get('DISTANCE')), 'brand':row.get('POLL_DIV_CD', '')})
            except (KeyError, TypeError, ValueError):
                continue
        return {'stations':sorted(stations, key=lambda s:s['price'])[:12], 'fetched_at':fetched,
                'radius_m':5000, 'attribution':'한국석유공사 오피넷',
                'notice':'조회 시점의 보고 가격 · 실제 판매가격/영업 여부는 주유소에서 확인하세요.'}

    def detail(self, station_id):
        if not isinstance(station_id, str) or not re.fullmatch(r'[A-Za-z0-9]{1,20}', station_id):
            raise OpinetError('주유소 ID를 확인하세요.')
        rows, fetched = self.request('detailById', {'id':station_id}, 1800)
        if not rows:
            raise OpinetError('주유소 상세정보가 없습니다.')
        row = rows[0]
        prices = row.get('OIL_PRICE', [])
        if isinstance(prices, dict):
            prices = [prices]
        return {'id':station_id, 'name':row.get('OS_NM',''), 'address':row.get('NEW_ADR') or row.get('VAN_ADR',''),
                'prices':[{'product':p['PRODCD'], 'product_name':PRODUCTS[p['PRODCD']], 'price':positive(p.get('PRICE')),
                           'date':p.get('TRADE_DT'), 'time':p.get('TRADE_TM')}
                          for p in prices if p.get('PRODCD') in PRODUCTS],
                'fetched_at':fetched, 'attribution':'한국석유공사 오피넷'}
