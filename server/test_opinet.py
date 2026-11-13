import io
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

from convoy_server import Convoy, ApiError
from opinet_service import Opinet, OpinetError, transform


class OpinetTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api=Opinet(Path(self.temp.name)/'cache.sqlite')
        self.config=patch.object(self.api,'config',return_value=('not-a-real-key',2))
        self.config.start();self.addCleanup(self.config.stop)

    @unittest.skipUnless(importlib.util.find_spec('pyproj'), 'Install requirements-opinet.txt for coordinate tests')
    def test_official_sample_coordinate_and_roundtrip(self):
        lon,lat=transform(314871.8,544012)
        self.assertTrue(127.03<lon<127.04 and 37.49<lat<37.50)
        x,y=transform(lon,lat,True)
        self.assertAlmostEqual(x,314871.8,places=2)
        self.assertAlmostEqual(y,544012,places=2)

    def test_shared_cache_and_restart_budget(self):
        payload={'RESULT':{'OIL':[{'PRICE':1800}]}}
        with patch('opinet_service.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(payload).encode())) as http:
            self.api.request('aroundAll',{'x':1},600)
            other=Opinet(self.api.database)
            with patch.object(other,'config',return_value=('not-a-real-key',2)):
                other.request('aroundAll',{'x':1},600)
                other.request('aroundAll',{'x':2},600)
                with self.assertRaises(OpinetError):other.request('aroundAll',{'x':3},600)
        self.assertEqual(http.call_count,2)

    def test_errors_never_expose_provider_url_or_key(self):
        with patch('opinet_service.urlopen',side_effect=URLError('secret URL not-a-real-key')):
            with self.assertRaises(OpinetError) as error:self.api.request('aroundAll',{},600)
        self.assertNotIn('not-a-real-key',str(error.exception))
        with closing(sqlite3.connect(self.api.database)) as db:
            self.assertEqual(db.execute('SELECT calls FROM quota').fetchone()[0],1)

    @unittest.skipUnless(importlib.util.find_spec('pyproj'), 'Install requirements-opinet.txt for coordinate tests')
    def test_invalid_prices_and_coordinates_are_not_markers(self):
        valid={'UNI_ID':'A1','OS_NM':'station','GIS_X_COOR':314871.8,'GIS_Y_COOR':544012,'PRICE':1800}
        with patch.object(self.api,'request',return_value=([valid,dict(valid,PRICE=0),dict(valid,PRICE='NaN'),dict(valid,GIS_X_COOR=0)],time.time())):
            result=self.api.nearby(37.49,127.03)
        self.assertEqual(len(result['stations']),1)
        with self.assertRaises(OpinetError):self.api.nearby(float('nan'),127)
        with self.assertRaises(OpinetError):self.api.detail('../bad')

    def test_auth_location_and_detail_prices(self):
        store=Convoy();a=store.handle('POST','/rooms',{'name':'A','destination':{'name':'end','latitude':36,'longitude':127}},'')
        path='/rooms/'+a['code']+'/fuel'
        with self.assertRaises(ApiError):store.handle('POST',path,{},'bad')
        with self.assertRaises(ApiError):store.handle('POST',path,{},a['token'])
        row={'OS_NM':'station','OIL_PRICE':[{'PRODCD':'B027','PRICE':'0','TRADE_DT':'20261113'}, {'PRODCD':'D047','PRICE':'1788','TRADE_TM':'174156'}]}
        with patch.object(self.api,'request',return_value=([row],time.time())):
            detail=self.api.detail('A1')
        self.assertIsNone(detail['prices'][0]['price'])
        self.assertEqual(detail['prices'][1]['price'],1788)


if __name__=='__main__':unittest.main()
